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

# Track per-profile log handler IDs for cleanup
_profile_log_handlers = {}


def _setup_profile_logging(profile_id: str, attempt: int = 1) -> int:
    """Add a dedicated log file for this profile."""
    log_file = f"logs/{profile_id}.log"
    handler_id = logger.add(
        log_file,
        level="DEBUG",
        filter=_make_profile_filter(profile_id),
        format="{time:HH:mm:ss.SSS} | {level: <8} | {module}:{function}:{line} | {message}",
        mode="w" if attempt == 1 else "a",  # Fresh file on first run, append on retries
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
) -> bool:
    """
    Execute the full automation pipeline for a single profile.
    
    Uses logger.contextualize(profile_id=X) so ALL downstream logs
    (opsec_workflow, interaction, device_adapter, etc.) are tagged
    and routed to the correct profile log file — not the terminal.
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
            
            from modules.opsec_workflow import OpSecBrowserManager
            from amazon.device_adapter import DeviceAdapter
            from amazon.core.session import SessionState
            
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
            session.load()
            
            device = profile.device
            
            # --- Outlook Setup ---
            if not session.identity and not session.completion_flags.get("outlook_created", False):
                logger.info("📬 Phase: Outlook Setup")
                
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
                if run_signup_flow(playwright_page, session, device):
                    logger.success("Signup complete")
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
            
            # Import the runner but PASS the pre-generated identity
            from amazon.outlook.run import run_outlook_signup_with_identity
            outlook_data = run_outlook_signup_with_identity(
                page, device, identity.to_outlook_dict()
            )
            
            if outlook_data == "RETRY":
                logger.warning(f"🔄 Outlook signaled retry (Attempt {attempt + 1})")
                if attempt < max_attempts - 1:
                    _time.sleep(2)
                    continue
                else:
                    return None, None
            
            if outlook_data and isinstance(outlook_data, dict):
                logger.success(f"✓ Outlook signup successful: {outlook_data.get('email_handle')}@outlook.com")
                
                generated_identity = Identity(
                    firstname=outlook_data['firstname'],
                    lastname=outlook_data['lastname'],
                    email=f"{outlook_data['email_handle']}@outlook.com",
                    password=outlook_data['password']
                )
                
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
    profile_id: str,
    lifecycle: ProfileLifecycleManager,
    identity_pool: IdentityPool,
    max_retries: int = 3
) -> bool:
    """
    Wrapper for run_profile_pipeline that handles retries.
    """
    for attempt_idx in range(max_retries):
        attempt = attempt_idx + 1
        
        # Stagger retries to avoid hammering services
        if attempt > 1:
            wait_time = random.uniform(5, 10)
            logger.info(f"⏳ Waiting {wait_time:.1f}s before retry {attempt}/{max_retries} for {profile_id}...")
            time.sleep(wait_time)
            
            # Increment retry count in metrics if already registered
            profile = lifecycle.get_profile(profile_id)
            if profile:
                profile.metrics.retry_count += 1
        
        success = run_profile_pipeline(profile_id, lifecycle, identity_pool, attempt=attempt)
        
        if success:
            return True
            
        if shutdown_event.is_set():
            logger.warning(f"Aborting retries for {profile_id} due to shutdown")
            break
            
        if attempt < max_retries:
            logger.warning(f"❌ Attempt {attempt} failed for {profile_id}. Queueing retry...")
        else:
            logger.error(f"❌ All {max_retries} attempts failed for {profile_id}")
            
    return False


def main():
    parser = argparse.ArgumentParser(description="Amazon V3 Orchestrator")
    parser.add_argument("--profiles", nargs="+", required=True, help="List of Profile IDs")
    parser.add_argument("--concurrency", type=int, default=3, help="Max concurrent profiles")
    parser.add_argument("--pool-size", type=int, default=5, help="Identity pre-generation pool size")
    parser.add_argument("--country", type=str, default="US", help="Country code for identity generation")
    parser.add_argument("--max-retries", type=int, default=3, help="Max retries per profile (default: 3)")
    
    args = parser.parse_args()
    
    # ──────────────────────────────────────────────────
    # STEP 1: Initial cleanup
    # ──────────────────────────────────────────────────
    kill_zombie_processes()
    
    # ──────────────────────────────────────────────────
    # STEP 2: Pre-warm identity pool
    # --------------------------------------------------
    # Optimization: Don't over-generate identities if we only have a few profiles.
    # We want enough to cover concurrency plus a small buffer for instantaneous retries.
    calculated_pool_size = min(args.pool_size, len(args.profiles) + 1)
    
    identity_pool = IdentityPool(
        pool_size=calculated_pool_size, 
        country_code=args.country
    )
    # Generate enough identities for all profiles BEFORE any browser starts
    identity_pool.warm_up(count=len(args.profiles))
    identity_pool.start_background_generation()
    
    # ──────────────────────────────────────────────────
    # STEP 3: Initialize lifecycle manager
    # ──────────────────────────────────────────────────
    lifecycle = ProfileLifecycleManager(max_concurrent=args.concurrency)
    
    # Register all profiles
    for pid in args.profiles:
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
    logger.info(
        f"🌟 Starting V3 Orchestrator: {len(args.profiles)} profiles, "
        f"concurrency={args.concurrency}, pool_size={args.pool_size}"
    )
    
    results = {}
    start_time = time.time()
    
    with ThreadPoolExecutor(
        max_workers=args.concurrency,
        thread_name_prefix="worker"
    ) as executor:
        futures_map = {}
        for pid in args.profiles:
            # ──────────────────────────────────────────────
            # STAGGERED LAUNCH to avoid AdsPower rate limits
            # ──────────────────────────────────────────────
            if len(args.profiles) > 1 and pid != args.profiles[0]:
                stagger_wait = random.uniform(2, 5)
                logger.info(f"⏳ Staggering: waiting {stagger_wait:.1f}s before starting {pid}...")
                time.sleep(stagger_wait)
                
            future = executor.submit(
                run_profile_with_retry,
                pid,
                lifecycle,
                identity_pool,
                max_retries=args.max_retries
            )
            futures_map[future] = pid
        
        for future in as_completed(futures_map):
            pid = futures_map[future]
            try:
                success = future.result()
                results[pid] = success
                status = "✅ SUCCESS" if success else "❌ FAILED"
                logger.info(f"{status}: Profile {pid}")
            except Exception as e:
                results[pid] = False
                logger.error(f"💥 Profile {pid} crashed: {e}")
    
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
