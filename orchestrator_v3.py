"""
Amazon Automation V3 Orchestrator

Replaces the subprocess-based orchestrator with an in-process worker model.
Uses pre-warmed identity pool and profile lifecycle management.

Key improvements over V2:
    1. Identity pre-generation BEFORE browser launch (eliminates 3-5s gap)
    2. In-process execution (saves ~50MB RAM per profile vs subprocess)
    3. Deterministic profile lifecycle (no ghost sessions)
    4. Shared resource management (single Playwright runtime)
    5. Performance metrics and observability
    6. Graceful shutdown with cleanup guarantees
    7. Smart retry with exponential backoff
"""

import asyncio
import argparse
import os
import sys
import time
import signal
import threading
import traceback
import random
from concurrent.futures import ThreadPoolExecutor, as_completed
from loguru import logger

# Signal to downstream modules that logging is managed by the orchestrator
# This prevents modules/config.py from adding its own stdout handlers
os.environ["ORCHESTRATOR_LOGGING"] = "1"

# Configure paths (same as run.py — ensures both `amazon.xxx` and `xxx` imports work)
root_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(root_dir)

if root_dir not in sys.path:
    sys.path.insert(0, root_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

# --- Move all project-local imports to top to avoid import deadlocks in threads ---
try:
    from modules.opsec_workflow import OpSecBrowserManager
    from amazon.device_adapter import DeviceAdapter
    from amazon.core.session import SessionState
    from amazon.outlook.run import run_outlook_signup_with_identity
    from amazon.identity_manager import Identity
    import agentql
    logger.info("✅ All core modules pre-imported successfully")
except Exception as e:
    logger.error(f"❌ Failed to pre-import core modules: {e}")
    # Don't exit here, let it fail gracefully in the pipeline if needed

# ──────────────────────────────────────────────────────────────
# LOG ROUTING via loguru.contextualize()
# ──────────────────────────────────────────────────────────────
# loguru.contextualize(profile_id=X) stores the profile_id in
# the log record's `extra` dict. This works across ALL downstream
# module logs — no thread-local hacks, no missed messages.
#
# Routing:
#   Terminal:   only records where extra["profile_id"] is absent
#   Profile:    only records where extra["profile_id"] matches
#   Master log: ALL records (no filter)
# ──────────────────────────────────────────────────────────────

# Global shutdown event — workers check this to exit on Ctrl+C
shutdown_event = threading.Event()


def _terminal_filter(record):
    """Terminal: only show messages that are NOT from a profile worker."""
    return "profile_id" not in record["extra"]


def _make_profile_filter(target_profile_id: str):
    """Create a filter for a specific profile's log file."""
    def _filter(record):
        return record["extra"].get("profile_id") == target_profile_id
    return _filter


# Configure logging — REMOVE ALL previous handlers first
logger.remove()
os.makedirs("logs", exist_ok=True)

# 1. Terminal: orchestrator-level only (clean, short format)
logger.add(
    sys.stderr,
    level="INFO",
    format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{message}</cyan>",
    filter=_terminal_filter,
)

# 2. Master log: everything from all threads (full detail)
def _master_format(record):
    """Format with profile_id tag if present."""
    pid = record["extra"].get("profile_id", "orchestrator")
    return (
        "{time:HH:mm:ss.SSS} | {level: <8} | "
        f"{pid:>12} | "
        "{module}:{function}:{line} | {message}\n{exception}"
    )

logger.add(
    "logs/orchestrator_{time:YYYY-MM-DD}.log",
    level="DEBUG",
    rotation="10 MB",
    retention="7 days",
    format=_master_format,
)

from core.identity_pool import IdentityPool, PooledIdentity
from core.profile_lifecycle import (
    ProfileLifecycleManager,
    ProfileState,
    ManagedProfile
)
from utils.cleanup import kill_zombie_processes
from modules.adspower import AdsPowerProfileManager
from modules.proxy import get_proxy_config

# Track per-profile log handler IDs for cleanup
_profile_log_handlers = {}

# Shared state for thread-safe pacing
_creation_lock = threading.Lock()
_last_creation_time = [0.0]
_stagger_lock = threading.Lock()
_last_launch_time = [0.0]
_first_launch = [True]


class EmailPool:
    """
    Thread-safe pool of pre-existing Outlook email credentials.

    Reads from a file formatted as one ``email:password`` per line.
    Lines already prefixed with ``#USED:`` are skipped.
    When an email is acquired it is immediately rewritten with the
    ``#USED:`` prefix so no other worker can claim the same address.
    """

    def __init__(self, emails_file: str = "emails/emails.txt"):
        self.emails_file = emails_file
        self._lock = threading.Lock()

    def acquire(self) -> dict | None:
        """
        Pop one unused email credential from the file.

        The line is atomically rewritten as ``#USED:<original>`` before
        returning so concurrent workers never see the same address.

        Returns:
            dict with keys ``email`` and ``password``, or ``None`` when
            the pool is exhausted.
        """
        with self._lock:
            try:
                with open(self.emails_file, "r") as f:
                    lines = f.readlines()
            except FileNotFoundError:
                logger.error(f"Emails file not found: {self.emails_file}")
                return None

            for i, line in enumerate(lines):
                stripped = line.strip()
                # Skip blank lines, comments, and already-consumed entries
                if not stripped or stripped.startswith("#"):
                    continue

                parts = stripped.split(":", 1)
                if len(parts) != 2:
                    logger.warning(f"Skipping malformed email line: {stripped}")
                    continue

                email, password = parts[0].strip(), parts[1].strip()

                # Mark consumed before returning
                lines[i] = f"#USED:{stripped}\n"
                try:
                    with open(self.emails_file, "w") as f:
                        f.writelines(lines)
                except Exception as e:
                    logger.error(f"Failed to mark email as used: {e}")
                    return None

                logger.info(f"📧 Acquired email from pool: {email}")
                return {"email": email, "password": password}

            logger.error("❌ Email pool exhausted — no unused emails remaining!")
            return None

    def available_count(self) -> int:
        """Return the number of unused emails still in the file."""
        try:
            with open(self.emails_file, "r") as f:
                return sum(
                    1 for line in f
                    if line.strip() and not line.strip().startswith("#") and ":" in line
                )
        except FileNotFoundError:
            return 0


def _setup_profile_logging(profile_id: str, attempt: int = 1) -> int:
    """Add a dedicated log file for this profile."""
    log_file = f"logs/{profile_id}.log"
    handler_id = logger.add(
        log_file,
        level="DEBUG",
        filter=_make_profile_filter(profile_id),
        format="{time:HH:mm:ss.SSS} | {level: <8} | {module}:{function}:{line} | {message}",
        mode="w" if attempt == 1 else "a",  # Fresh file on first run, append on retries
        encoding="utf-8",                   # Critical to prevent UnicodeEncodeError on some systems
    )
    _profile_log_handlers[profile_id] = handler_id
    return handler_id


def _teardown_profile_logging(profile_id: str):
    """Remove a profile's log handler."""
    handler_id = _profile_log_handlers.pop(profile_id, None)
    if handler_id is not None:
        try:
            logger.remove(handler_id)
        except ValueError:
            pass



def run_profile_pipeline(
    profile_id: str,
    lifecycle: ProfileLifecycleManager,
    identity_pool: IdentityPool,
    attempt: int = 1,
    skip_outlook_signup: bool = False,
    email_pool: "EmailPool | None" = None,
    drop_on_phone: bool = False,
) -> bool | str:
    """
    Execute the full automation pipeline for a single profile.

    Uses logger.contextualize(profile_id=X) so ALL downstream logs
    (opsec_workflow, interaction, device_adapter, etc.) are tagged
    and routed to the correct profile log file — not the terminal.

    Args:
        skip_outlook_signup: When True the Outlook *signup* flow is
            skipped and an existing credential from ``email_pool`` is
            used to sign in instead.
        email_pool: Required when ``skip_outlook_signup`` is True.
    """
    _setup_profile_logging(profile_id, attempt=attempt)
    
    # contextualize() tags every log record from this thread with profile_id
    # This is what makes the terminal filter work for ALL downstream modules
    with logger.contextualize(profile_id=profile_id):
        if attempt > 1:
            logger.info(f"🔄 --- RETRY ATTEMPT {attempt} ---")
        
        profile = lifecycle.register_profile(profile_id)
        
        def _check_shutdown():
            """Check if shutdown was requested. Returns True if should abort."""
            if shutdown_event.is_set():
                logger.warning("Shutdown requested, aborting pipeline")
                return True
            return False
        
        try:
            # ──────────────────────────────────────────────
            # PHASE 0: Identity Acquisition (BEFORE browser)
            # ──────────────────────────────────────────────
            logger.info("🆔 Acquiring pre-generated identity...")
            identity = identity_pool.acquire(profile_id, timeout=30)
            
            if not identity:
                logger.error("No identity available in pool!")
                profile.transition_to(ProfileState.ERROR, "No identity available")
                return False
            
            profile.identity = identity
            logger.success(
                f"Identity ready: {identity.firstname} {identity.lastname} "
                f"({identity.email_handle})"
            )
            
            if _check_shutdown(): return False
            
            # ──────────────────────────────────────────────
            # PHASE 1: Browser Launch
            # ──────────────────────────────────────────────
            profile.transition_to(ProfileState.LAUNCHING, "Starting browser")
            logger.info("Launching browser...")
            
            manager = OpSecBrowserManager(profile_id)
            
            try:
                manager.start_browser(headless=False)
                
                playwright_page = None
                if manager.context and manager.context.pages:
                    playwright_page = manager.context.pages[0]
                elif manager.context:
                    playwright_page = manager.context.new_page()
                
                if not playwright_page:
                    raise RuntimeError("Failed to acquire browser page")
                
                profile.browser_manager = manager
                profile.page = playwright_page
                profile.device = DeviceAdapter(playwright_page)
                
                profile.transition_to(ProfileState.READY, "Browser connected")
                logger.success("Browser connected and ready")
                
            except Exception as e:
                logger.error(f"Browser launch failed: {e}")
                profile.transition_to(ProfileState.ERROR, f"Launch failed: {e}")
                manager.stop_browser()
                identity_pool.release(profile_id, success=False, notes="Browser launch failed")
                return False
            
            if _check_shutdown():
                _cleanup_profile(profile, manager, identity_pool, success=False)
                return False
            
            # ──────────────────────────────────────────────
            # PHASE 2: Execute Automation
            # ──────────────────────────────────────────────
            profile.transition_to(ProfileState.WORKING, "Starting automation")
            
            session = SessionState(profile_id)
            
            device = profile.device
            
            # --- Outlook Setup ---
            if not session.identity and not session.completion_flags.get("outlook_created", False):
                logger.info("📬 Phase: Outlook Setup")

                if skip_outlook_signup:
                    # ── Sign-in path: consume a pre-existing email credential ──
                    logger.info("📧 skip-outlook-signup=True — using existing email credential")
                    if email_pool is None:
                        logger.error("email_pool is required when skip_outlook_signup=True")
                        _cleanup_profile(profile, manager, identity_pool, success=False)
                        return False

                    email_data = email_pool.acquire()
                    if not email_data:
                        logger.error("Email pool exhausted — cannot proceed without an Outlook account")
                        profile.transition_to(ProfileState.ERROR, "Email pool exhausted")
                        _cleanup_profile(profile, manager, identity_pool, success=False)
                        return False

                    generated_identity, new_page = _run_outlook_login_with_email(
                        manager, playwright_page, device, email_data,
                        country_code=identity_pool.country_code,
                    )
                else:
                    # ── Default path: sign-up with pre-warmed identity ──
                    generated_identity, new_page = _run_outlook_with_preloaded_identity(
                        manager, playwright_page, device, identity
                    )

                if generated_identity and new_page:
                    session.update_identity(generated_identity)
                    session.update_flag("outlook_created", True)
                    playwright_page = new_page
                    device.page = playwright_page
                    profile.page = playwright_page
                    identity_pool.mark_outlook_done(profile_id, generated_identity.email)
                    logger.success(f"Outlook done: {generated_identity.email}")
                else:
                    logger.error("Outlook setup failed")
                    profile.transition_to(ProfileState.ERROR, "Outlook setup failed")
                    _cleanup_profile(profile, manager, identity_pool, success=False)
                    return False
            
            if _check_shutdown():
                _cleanup_profile(profile, manager, identity_pool, success=False)
                return False
            
            # --- eBook Selection ---
            if not session.completion_flags.get("product_selected", False):
                logger.info("🛒 Phase: Product Selection")
                from amazon.actions.ebook_search_flow import run_ebook_search_flow
                if run_ebook_search_flow(playwright_page, device, session):
                    session.update_flag("product_selected", True)
                    logger.success("Product selected")
                else:
                    logger.error("Product Selection failed")
                    _cleanup_profile(profile, manager, identity_pool, success=False)
                    return False
            
            if _check_shutdown():
                _cleanup_profile(profile, manager, identity_pool, success=False)
                return False
            
            # --- Amazon Signup ---
            if not session.completion_flags.get("amazon_signup", False):
                logger.info("👤 Phase: Signup")
                from amazon.actions.signup_flow import run_signup_flow
                signup_res = run_signup_flow(playwright_page, session, device, drop_on_phone=drop_on_phone)
                
                if signup_res is True:
                    logger.success("Signup complete")
                elif signup_res == "DROPPED_PHONE":
                    logger.warning("📱 Profile DROPPED: Encountered Amazon phone number verification.")
                    session.update_flag("dropped_on_phone", True)
                    _cleanup_profile(profile, manager, identity_pool, success=False)
                    return "DROPPED_PHONE"
                else:
                    logger.error("Signup failed")
                    _cleanup_profile(profile, manager, identity_pool, success=False)
                    return False
            
            if _check_shutdown():
                _cleanup_profile(profile, manager, identity_pool, success=False)
                return False
            
            # --- Developer Registration ---
            if not session.completion_flags.get("dev_registration", False):
                logger.info("🛠️ Phase: Developer Registration")
                playwright_page = device.page
                from amazon.actions.developer_registration import run_developer_registration
                if run_developer_registration(playwright_page, session, device):
                    logger.success("Developer Registration complete")
                else:
                    logger.error("Developer Registration failed")
                    _cleanup_profile(profile, manager, identity_pool, success=False)
                    return False
            
            if _check_shutdown():
                _cleanup_profile(profile, manager, identity_pool, success=False)
                return False
            
            # --- 2FA Setup ---
            if not session.completion_flags.get("2fa_enabled", False):
                logger.info("🔐 Phase: 2FA Activation")
                playwright_page = device.page
                from amazon.actions.two_step_verification import run_2fa_setup_flow
                if run_2fa_setup_flow(playwright_page, session, device):
                    logger.success("2FA complete")
                else:
                    logger.error("2FA failed")
                    _cleanup_profile(profile, manager, identity_pool, success=False)
                    return False

            if _check_shutdown():
                _cleanup_profile(profile, manager, identity_pool, success=False)
                return False

            # --- Identity Verification (IDV) ---
            if not session.completion_flags.get("idv_submitted", False):
                logger.info("🪪 Phase: Identity Verification")
                playwright_page = device.page
                from amazon.actions.identity_verification import run_identity_verification
                if run_identity_verification(playwright_page, session, device):
                    logger.success("Identity Verification submitted")
                else:
                    logger.error("Identity Verification failed")
                    _cleanup_profile(profile, manager, identity_pool, success=False)
                    return False

            # ──────────────────────────────────────────────
            # PHASE 3: Success
            # ──────────────────────────────────────────────
            logger.success("🏁 ALL PHASES COMPLETE!")
            _cleanup_profile(profile, manager, identity_pool, success=True)
            return True
            
        except Exception as e:
            logger.exception(f"💥 Unexpected error: {e}")
            profile.transition_to(ProfileState.ERROR, str(e))
            
            try:
                if profile.browser_manager:
                    profile.browser_manager.stop_browser()
            except:
                pass
            
            identity_pool.release(profile_id, success=False, notes=str(e))
            return False
            
        finally:
            _teardown_profile_logging(profile_id)


def _run_outlook_login_with_email(manager, page, device, email_data: dict, country_code: str = "US"):
    """
    Run Outlook *sign-in* with an existing ``email:password`` credential.

    After a successful login a **full** identity is generated via
    ``IdentityGenerator`` (proper name, address, DOB) and the pool email
    and password are injected into it.  This ensures downstream stages
    (Amazon signup, developer registration, IDV) receive realistic person
    data instead of using the email address as a name.

    Args:
        manager:      OpSecBrowserManager
        page:         Current Playwright page
        device:       DeviceAdapter
        email_data:   Dict with keys ``email`` and ``password``
        country_code: Country for identity generation (default ``"US"``).

    Returns:
        Tuple of ``(Identity, page)`` on success, or ``(None, None)``.
    """
    import time as _time
    from amazon.identity_manager import Identity

    email = email_data.get("email", "")
    password = email_data.get("password", "")
    logger.info(f"📧 Starting Outlook Login for: {email}")

    # Switch to a fresh tab
    try:
        new_page = manager.context.new_page()
        if page and not page.is_closed():
            page.close()
        page = new_page
        device.page = page
    except Exception as e:
        logger.warning(f"Could not recycle tab for Outlook login: {e}")

    max_attempts = 3
    for attempt in range(max_attempts):
        logger.info(f"📧 Outlook Login Attempt {attempt + 1}/{max_attempts}")
        try:
            if page.is_closed():
                page = manager.context.new_page()
                device.page = page

            from amazon.outlook_login.run import run_outlook_login
            outlook_data = run_outlook_login(page, device, email_data)

            if outlook_data == "RETRY":
                logger.warning(f"🔄 Outlook login signaled RETRY (Attempt {attempt + 1})")
                if attempt < max_attempts - 1:
                    # Close old tab and open fresh one for retry
                    try:
                        if not page.is_closed():
                            page.close()
                        page = manager.context.new_page()
                        device.page = page
                    except Exception as e:
                        logger.warning(f"Could not recycle tab for retry: {e}")
                    _time.sleep(2)
                    continue
                return None, None

            if outlook_data and isinstance(outlook_data, dict):
                logger.success(f"✓ Outlook login successful: {email}")

                # Generate a full, realistic identity then inject the pool email.
                try:
                    from modules.identity_generator import IdentityGenerator
                    ig = IdentityGenerator()
                    base = ig.generate_identity(country_code)
                    firstname = base["first_name"]
                    lastname = base["last_name"]
                    address = base.get("address", "")
                    city = base.get("city", "")
                    zip_code = base.get("zip", "")
                    state = base.get("state", "")
                    phone = base.get("phone", "")
                    country_name_map = {
                        "US": "United States", "AU": "Australia", "GB": "United Kingdom",
                        "CA": "Canada", "DE": "Germany", "FR": "France", "IT": "Italy",
                    }
                    country_full = country_name_map.get(country_code.upper(), country_code)
                    logger.info(
                        f"🆔 Generated identity for signin: {firstname} {lastname} "
                        f"({city}, {country_full})"
                    )
                except Exception as gen_err:
                    logger.warning(f"Identity generation failed, falling back to email handle: {gen_err}")
                    email_handle = email.split("@")[0]
                    firstname, lastname = email_handle, ""
                    address, city, zip_code, state, country_full, phone = "", "", "", "", country_code, ""

                generated_identity = Identity(
                    firstname=firstname,
                    lastname=lastname,
                    email=email,
                    password=password,
                    address_line1=address,
                    city=city,
                    zip_code=zip_code,
                    state=state,
                    country=country_full,
                    phone=phone,
                )
                final_page = manager.context.new_page()
                page.close()
                return generated_identity, final_page
            else:
                logger.error("Outlook login returned no data")
                if attempt < max_attempts - 1:
                    continue
                return None, None

        except Exception as e:
            logger.error(f"Outlook login attempt {attempt + 1} raised: {e}")
            if attempt < max_attempts - 1:
                _time.sleep(2)
                continue
            return None, None

    return None, None


def _run_outlook_with_preloaded_identity(manager, page, device, identity: PooledIdentity):
    """
    Run Outlook signup with a PRE-GENERATED identity.
    
    This is the key optimization: instead of generating identity inside the Outlook
    flow (which blocks while browser is open), we pass the pre-warmed identity
    directly to the signup runner.
    
    Args:
        manager: OpSecBrowserManager
        page: Current Playwright page
        device: DeviceAdapter
        identity: Pre-generated PooledIdentity
        
    Returns:
        Tuple of (Identity, page) or (None, None)
    """
    import time as _time
    from amazon.identity_manager import Identity
    
    logger.info("📧 Starting Outlook Signup with pre-loaded identity...")
    
    # Switch to fresh tab
    try:
        new_outlook_page = manager.context.new_page()
        if page and not page.is_closed():
            page.close()
        page = new_outlook_page
        device.page = page
    except Exception as e:
        logger.warning(f"Could not recycle tab for Outlook: {e}")
    
    max_attempts = 3
    for attempt in range(max_attempts):
        logger.info(f"📧 Outlook Signup Attempt {attempt + 1}/{max_attempts}")
        
        try:
            if page.is_closed():
                page = manager.context.new_page()
                device.page = page
            
            logger.info("📧 Handing over to Outlook signup runner...")
            # Runner is pre-imported at top of file
            outlook_data = run_outlook_signup_with_identity(
                page, device, identity.to_outlook_dict()
            )
            logger.info("📧 Outlook signup runner returned.")
            
            if outlook_data == "RETRY":
                logger.warning(f"🔄 Outlook signaled retry (Attempt {attempt + 1})")
                if attempt < max_attempts - 1:
                    # Close old tab and open fresh one for retry
                    try:
                        if not page.is_closed():
                            page.close()
                        page = manager.context.new_page()
                        device.page = page
                    except Exception as e:
                        logger.warning(f"Could not recycle tab for retry: {e}")
                    _time.sleep(2)
                    continue
                else:
                    return None, None
            
            if outlook_data and isinstance(outlook_data, dict):
                logger.success(f"✓ Outlook signup successful: {outlook_data.get('email_handle')}@outlook.com")
                
                # Use the complete identity conversion from PooledIdentity
                generated_identity = identity.to_amazon_identity()
                # Ensure the email handle reflects any changes during execution (though unlikely)
                generated_identity.email = f"{outlook_data['email_handle']}@outlook.com"

                
                final_page = manager.context.new_page()
                page.close()
                
                return generated_identity, final_page
            else:
                logger.error("Outlook signup failed (no data returned)")
                if attempt < max_attempts - 1:
                    continue
                return None, None
                
        except Exception as e:
            logger.error(f"Outlook step failed on attempt {attempt + 1}: {e}")
            if attempt < max_attempts - 1:
                _time.sleep(2)
                continue
            return None, None
    
    return None, None


def _cleanup_profile(profile: ManagedProfile, manager, identity_pool: IdentityPool, success: bool):
    """Deterministic cleanup for a profile's resources."""
    try:
        if profile.state == ProfileState.WORKING:
            profile.transition_to(ProfileState.COOLING, "Task finished")
        
        # Stop browser
        if manager:
            profile.transition_to(ProfileState.STOPPING, "Shutting down browser")
            manager.stop_browser()
            profile.browser_manager = None  # Ensure it's cleared for retry
        
        # Release identity
        identity_pool.release(
            profile.profile_id, 
            success=success,
            notes=profile.last_error if not success else None
        )
        
        # Final state
        target = ProfileState.COMPLETED if success else ProfileState.IDLE
        profile.transition_to(target, "Cleanup complete")
        
    except Exception as e:
        logger.warning(f"Cleanup error for {profile.profile_id}: {e}")


def run_profile_with_retry(
    task_input: str | int,
    lifecycle: ProfileLifecycleManager,
    identity_pool: IdentityPool,
    max_retries: int = 3,
    skip_outlook_signup: bool = False,
    email_pool: "EmailPool | None" = None,
    drop_on_phone: bool = False,
    skip_delete: bool = False,
    # New arguments for automatic creation
    os_type: str = "windows",
    country: str = "AU",
) -> bool:
    """
    Wrapper for run_profile_pipeline that handles retries and on-demand creation.
    """
    is_automatic = isinstance(task_input, int)
    task_idx = task_input if is_automatic else 0
    last_known_profile_id = None if is_automatic else str(task_input)

    try:
        for attempt_idx in range(max_retries):
            attempt = attempt_idx + 1
            
            # --- 1. Resolve/Create Profile ---
            current_profile_id: str | None = last_known_profile_id
            
            if is_automatic:
                # If we're retrying, cleanup the failed profile from previous attempt
                if last_known_profile_id:
                    logger.info(f"🔄 Cleaning up failed profile {last_known_profile_id} before retry...")
                    try:
                        AdsPowerProfileManager().stop_profile(last_known_profile_id)
                        if not skip_delete:
                            AdsPowerProfileManager().delete_profile(last_known_profile_id)
                    except: pass
                    last_known_profile_id = None

                # Create profile with pacing to avoid AdsPower API rate limits
                while True:
                    if shutdown_event.is_set(): return False
                    
                    with _creation_lock:
                        elapsed = time.time() - _last_creation_time[0]
                        # Respect a 3.5s gap between creation API calls (AdsPower is sensitive)
                        wait = max(0.0, 3.5 - elapsed)
                        if wait > 0:
                            time.sleep(wait)
                        
                        manager = AdsPowerProfileManager()
                        # Name includes task index and timestamp for uniqueness
                        name = f"Auto_{os_type.capitalize()}_{int(time.time())}_{task_idx + 1}"
                        proxy_config = get_proxy_config(country=country.lower())
                        
                        logger.info(f"🆕 [Task {task_idx+1}] Creating automatic profile: {name} (Attempt {attempt})")
                        created_pid = manager.create_profile_v2(
                            name=name,
                            os_type=os_type,
                            proxy_config=proxy_config
                        )
                        _last_creation_time[0] = time.time()
                    
                    if not created_pid:
                        err = getattr(manager, 'last_error', "") or ""
                        if "limit" in err.lower() and ("exceed" in err.lower() or "delete" in err.lower()):
                            logger.warning(f"⚠️ [Task {task_idx+1}] AdsPower account full (limit reached). Waiting 30s for a slot...")
                            time.sleep(30)
                            continue # Retry creation until slot is available
                        else:
                            # Standard error (rate limit, connection, etc.)
                            logger.error(f"❌ [Task {task_idx+1}] Failed to create profile on attempt {attempt}")
                            break # Fall back to outer retry loop
                    else:
                        break # Success!
                
                if not created_pid:
                    if attempt < max_retries:
                        time.sleep(random.uniform(5, 10))
                        continue
                    return False
                
                current_profile_id = created_pid
                last_known_profile_id = current_profile_id
                logger.info(f"✅ [Task {task_idx+1}] Created profile: {current_profile_id}")

            if current_profile_id is None:
                continue

            # --- 2. Stagger Browser Launch ---
            # Even if created, we stagger the actual launch to avoid high CPU spikes 
            # and AdsPower/CDP websocket conflicts.
            with _stagger_lock:
                if _first_launch[0]:
                    _first_launch[0] = False
                else:
                    # 5-10s gap between browser starts
                    gap = random.uniform(5, 10)
                    elapsed = time.time() - _last_launch_time[0]
                    wait = max(0.0, gap - elapsed)
                    if wait > 0:
                        logger.info(f"⏳ Staggering: waiting {wait:.1f}s before launching {current_profile_id}...")
                        time.sleep(wait)
                _last_launch_time[0] = time.time()

            # --- 3. Execute Pipeline ---
            result = run_profile_pipeline(
                current_profile_id, lifecycle, identity_pool,
                attempt=attempt,
                skip_outlook_signup=skip_outlook_signup,
                email_pool=email_pool,
                drop_on_phone=drop_on_phone,
            )

            if result is True:
                return True
            
            if result == "DROPPED_PHONE":
                logger.warning(f"⚠️ Profile {current_profile_id} was DROPPED terminaly. Skipping retries.")
                return False

            if shutdown_event.is_set():
                logger.warning(f"Aborting retries for {current_profile_id} due to shutdown")
                break

            if attempt < max_retries:
                logger.warning(f"❌ Attempt {attempt} failed for {current_profile_id}. Queueing retry...")
            else:
                logger.error(f"❌ All {max_retries} attempts failed for {current_profile_id}")

        return False
    finally:
        # Pre-emptive stop just in case pipeline crashed or finished without stopping
        if last_known_profile_id:
            try:
                AdsPowerProfileManager().stop_profile(last_known_profile_id)
            except: pass
            
            if not skip_delete and is_automatic:
                logger.info(f"🗑️ Final cleanup: Deleting automatic profile {last_known_profile_id}...")
                try:
                    AdsPowerProfileManager().delete_profile(last_known_profile_id)
                except Exception as e:
                    logger.error(f"Failed to delete profile {last_known_profile_id}: {e}")


def main():
    parser = argparse.ArgumentParser(description="Amazon V3 Orchestrator")
    parser.add_argument("--profiles", nargs="+", help="List of Profile IDs")
    parser.add_argument("--accounts", type=int, help="Number of profiles to create if --profiles is missing")
    parser.add_argument("--os", type=str, default="windows", choices=["windows", "mac", "android", "ios"], help="OS for new profiles")
    parser.add_argument("--concurrency", type=int, default=3, help="Max concurrent profiles")
    parser.add_argument("--pool-size", type=int, default=5, help="Identity pre-generation pool size")
    parser.add_argument("--country", type=str, default="AU", help="Country code for identity generation and proxy")
    parser.add_argument("--max-retries", type=int, default=3, help="Max retries per profile (default: 3)")
    parser.add_argument(
        "--skip-outlook-signup",
        action="store_true",
        default=False,
        help=(
            "Skip Outlook account creation and sign in with a pre-existing "
            "credential from --emails-file instead. Each email is marked as "
            "#USED: in the file after it is consumed."
        ),
    )
    parser.add_argument(
        "--emails-file",
        type=str,
        default="emails/emails.txt",
        help="Path to the email credentials file used when --skip-outlook-signup is set (default: emails/emails.txt)",
    )
    parser.add_argument(
        "--drop-on-phone",
        action="store_true",
        help="Stop and drop the current profile if the phone number prompt appears in Amazon.",
    )
    parser.add_argument(
        "--skip-delete",
        action="store_true",
        help="Skip automatic deletion of the AdsPower profile after the automation finishes or is dropped.",
    )

    args = parser.parse_args()

    # ──────────────────────────────────────────────────
    # STEP -1: Override country-specific configs
    # ──────────────────────────────────────────────────
    import config
    # Map country code to OnlineSim numeric country ID if possible
    # (Simplified: just use the code as string first, mobile_verification handles it)
    if args.country:
        logger.info(f"🌍 Setting global country context to: {args.country}")
        # OnlineSim country IDs: AU=61, US=1, GB=44, etc.
        country_id_map = {"AU": 61, "US": 1, "GB": 44, "CA": 1, "DE": 49, "FR": 33}
        config.ONLINESIM_DEFAULT_COUNTRY = country_id_map.get(args.country.upper(), 1)

    # ──────────────────────────────────────────────────
    # STEP 0: Resolve Work Items
    # ──────────────────────────────────────────────────
    # If --profiles is provided, we use those specific profiles.
    # If only --accounts is provided, we will create profiles one-by-one 
    # inside the worker threads based on concurrency.
    initial_profiles = args.profiles or []
    
    # tasks will be a list of either Profile IDs (strings) or placeholder indices (integers)
    tasks = []
    if initial_profiles:
        tasks = initial_profiles
    elif args.accounts:
        tasks = list(range(args.accounts))
        logger.info(f"🆕 No profiles specified. Will create {args.accounts} new profiles on-demand (max {args.concurrency} concurrent).")
    else:
        logger.error("❌ Either --profiles or --accounts must be specified.")
        sys.exit(1)
    
    # ──────────────────────────────────────────────────
    # STEP 0b: Initialise email pool (if signin mode)
    # ──────────────────────────────────────────────────
    email_pool = None
    if args.skip_outlook_signup:
        email_pool = EmailPool(emails_file=args.emails_file)
        available = email_pool.available_count()
        if available == 0:
            logger.error(
                f"❌ --skip-outlook-signup requested but no unused emails "
                f"found in {args.emails_file}. Add credentials or remove #USED: prefixes."
            )
            sys.exit(1)
        logger.info(
            f"📧 Outlook signin mode: {available} unused email(s) available in {args.emails_file}"
        )

    # ──────────────────────────────────────────────────
    # STEP 1: Initial cleanup
    # ──────────────────────────────────────────────────
    kill_zombie_processes()
    
    # ──────────────────────────────────────────────────
    # STEP 2: Pre-warm identity pool
    # --------------------------------------------------
    # Optimization: Don't over-generate identities if we only have a few tasks.
    # We want enough to cover concurrency plus a small buffer for instantaneous retries.
    calculated_pool_size = min(args.pool_size, len(tasks) + 1)
    
    identity_pool = IdentityPool(
        pool_size=calculated_pool_size, 
        country_code=args.country
    )
    # Generate enough identities for all tasks BEFORE any browser starts
    identity_pool.warm_up(count=len(tasks))
    identity_pool.start_background_generation()
    
    # ──────────────────────────────────────────────────
    # STEP 3: Initialize lifecycle manager
    # ──────────────────────────────────────────────────
    lifecycle = ProfileLifecycleManager(max_concurrent=args.concurrency)
    
    # Register any pre-existing profiles
    for pid in initial_profiles:
        lifecycle.register_profile(pid)
    
    # ──────────────────────────────────────────────────
    # STEP 4: Signal handling
    # ──────────────────────────────────────────────────
    def signal_handler(sig, frame):
        if shutdown_event.is_set():
            # Second Ctrl+C — force kill immediately
            logger.warning("⚡ Force exit!")
            try:
                kill_zombie_processes()
            except:
                pass
            os._exit(1)
        
        shutdown_event.set()
        logger.warning("🛑 Shutdown requested. Stopping all browsers...")
        
        # Stop background identity generation
        identity_pool.stop_background_generation()
        
        # Cancel pending futures that haven't started
        for future in list(futures_map.keys()):
            future.cancel()
        
        # Stop all browsers — this is the critical cleanup
        lifecycle.cleanup_all()
        
        # Kill any remaining zombie processes
        kill_zombie_processes()
        
        # Exit immediately — workers are dead (browsers closed), 
        # no point waiting for ThreadPoolExecutor to join them
        logger.info("🏁 Shutdown complete.")
        os._exit(0)
    
    # Placeholder — populated after futures are submitted
    futures_map = {}
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # ──────────────────────────────────────────────────
    # STEP 5: Execute with thread pool
    # ──────────────────────────────────────────────────
    # All profiles are submitted immediately so the executor can queue them.
    # Stagger is applied inside each worker right before it actually starts,
    # ensuring proper gaps without blocking the main submission loop.
    # This guarantees that as soon as a running profile finishes, the next
    # queued profile starts without any delay introduced by the main thread.
    # ──────────────────────────────────────────────────
    logger.info(
        f"🌟 Starting V3 Orchestrator: {len(tasks)} tasks, "
        f"concurrency={args.concurrency}, pool_size={args.pool_size}"
    )
    
    results = {}
    start_time = time.time()

    def _run_worker(task_input) -> bool:
        """Worker wrapper: run pipeline with retry and on-demand creation."""
        return run_profile_with_retry(
            task_input,
            lifecycle,
            identity_pool,
            max_retries=args.max_retries,
            skip_outlook_signup=args.skip_outlook_signup,
            email_pool=email_pool,
            drop_on_phone=args.drop_on_phone,
            skip_delete=args.skip_delete,
            os_type=args.os,
            country=args.country,
        )

    with ThreadPoolExecutor(
        max_workers=args.concurrency,
        thread_name_prefix="worker"
    ) as executor:
        # Submit ALL tasks upfront — the executor automatically queues
        # any beyond max_workers and starts them as slots free up.
        # If --accounts was used, only 'concurrency' profiles will be created at any one time.
        futures_map = {executor.submit(_run_worker, task): task for task in tasks}
        
        for future in as_completed(futures_map):
            task_info = futures_map[future]
            try:
                success = future.result()
                results[str(task_info)] = success
                status = "✅ SUCCESS" if success else "❌ FAILED"
                logger.info(f"{status}: Task {task_info}")
            except Exception as e:
                results[str(task_info)] = False
                logger.error(f"💥 Task {task_info} crashed: {e}")
    
    # ──────────────────────────────────────────────────
    # STEP 6: Summary
    # ──────────────────────────────────────────────────
    elapsed = time.time() - start_time
    success_count = sum(1 for v in results.values() if v)
    fail_count = len(results) - success_count
    
    identity_pool.stop_background_generation()
    
    # Get metrics
    metrics = lifecycle.get_metrics_summary()
    pool_stats = identity_pool.get_stats()
    
    logger.info("=" * 60)
    logger.info(f"🏁 ORCHESTRATOR COMPLETE")
    logger.info(f"   Time: {elapsed:.1f}s")
    logger.info(f"   Success: {success_count}/{len(results)}")
    logger.info(f"   Failed: {fail_count}/{len(results)}")
    logger.info(f"   Avg Launch: {metrics.get('avg_launch_time', 0):.1f}s")
    logger.info(f"   Avg Task: {metrics.get('avg_task_time', 0):.1f}s")
    logger.info(f"   Identities Consumed: {success_count + fail_count}")
    logger.info(f"   Identities Generated: {pool_stats.get('total_generated', 0)}")
    logger.info(f"   Total Errors: {metrics.get('total_errors', 0)}")
    logger.info("=" * 60)
    
    # Final cleanup
    lifecycle.cleanup_all()
    kill_zombie_processes()
    
    sys.exit(0 if fail_count == 0 else 1)


if __name__ == "__main__":
    main()
