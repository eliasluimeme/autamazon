"""
Passkey / Interruption Step Handler

Handles the passkey setup interruption from Microsoft during Outlook signup.

Flow:
  1. Use CDP WebAuthn to cancel the native passkey dialog (works across all platforms)
  2. Fallback: OS-level Escape via subprocess (macOS) / page navigation
  3. Wait for Microsoft to redirect to the "We couldn't create a passkey" error page
  4. Click "Cancel" on that error page (NOT "Try again")

Fallback chain (if primary cancel doesn't apply):
  1. Cached XPath selectors  (fastest)
  2. CSS selectors            (fast)
  3. AgentQL fallback         (slow but robust)
  4. get_by_role              (last resort)
  5. Navigate away            (nuclear option — ensures we leave the passkey page)
"""

import time
import platform
import subprocess
from loguru import logger

from amazon.outlook.queries import PASSKEY_STEP_QUERY
from amazon.outlook.utils.xpath_cache import (
    find_element,
    extract_and_cache_xpath,
    get_cached_xpath,
    DOMPATH_AVAILABLE,
)

# How many ESC rounds to attempt before giving up
_ESC_MAX_ROUNDS = 4
# Seconds to wait between checking whether the popup disappeared
_ESC_CHECK_INTERVAL = 0.8
# Track consecutive passkey attempts for loop detection
_passkey_attempt_count = 0
_MAX_PASSKEY_ATTEMPTS = 3


def setup_webauthn_bypass(page) -> bool:
    """
    Pre-emptively enable a virtual WebAuthn authenticator so the browser
    never shows the native passkey dialog.

    Call this ONCE after connecting to the browser, BEFORE navigating to
    any page that might trigger WebAuthn (e.g. Outlook signup).

    The virtual authenticator intercepts all WebAuthn requests and auto-rejects
    them (isUserVerified=False), causing the ceremony to fail silently.
    The browser never shows the OS-level "Choose where to save your passkey" dialog.

    Returns:
        True if the bypass was set up successfully, False otherwise.
    """
    try:
        cdp = page.context.new_cdp_session(page)

        # Enable the WebAuthn domain — this tells Chrome to use virtual authenticators
        cdp.send("WebAuthn.enable", {"enableUI": False})

        # Add a virtual authenticator that will auto-reject all credential requests
        result = cdp.send("WebAuthn.addVirtualAuthenticator", {
            "options": {
                "protocol": "ctap2",
                "transport": "internal",
                "hasResidentKey": True,
                "hasUserVerification": True,
                "isUserVerified": False,        # Simulate user declining
                "automaticPresenceSimulation": True,  # Auto-respond to requests
            }
        })
        authenticator_id = result.get("authenticatorId")
        logger.info(f"🔐 WebAuthn bypass active (authenticator: {authenticator_id})")

        # Don't detach the CDP session — it must stay alive for the authenticator to persist
        # Store the CDP session and authenticator ID on the page for later cleanup
        page._webauthn_cdp = cdp
        page._webauthn_authenticator_id = authenticator_id

        return True

    except Exception as e:
        logger.warning(f"⚠️ Could not set up WebAuthn bypass: {e}")
        return False


def cleanup_webauthn_bypass(page):
    """Clean up the WebAuthn bypass (call when done with signup)."""
    try:
        cdp = getattr(page, '_webauthn_cdp', None)
        auth_id = getattr(page, '_webauthn_authenticator_id', None)
        if cdp and auth_id:
            cdp.send("WebAuthn.removeVirtualAuthenticator", {"authenticatorId": auth_id})
            cdp.send("WebAuthn.disable")
            cdp.detach()
            page._webauthn_cdp = None
            page._webauthn_authenticator_id = None
            logger.debug("🔐 WebAuthn bypass cleaned up")
    except Exception as e:
        logger.debug(f"WebAuthn cleanup (non-critical): {e}")


def handle_passkey_step(page, device, agentql_page=None) -> bool:
    """
    Handle the Passkey Setup interruption.

    The native macOS Touch ID / Windows Hello / Chrome passkey dialog is an
    OS-level popup that cannot be dismissed by Playwright's page.keyboard.press().
    We use CDP WebAuthn commands to cancel the ceremony, then fall back to
    OS-level escape and page navigation.
    """
    global _passkey_attempt_count
    _passkey_attempt_count += 1
    logger.info(f"🚫 Handling Passkey/Interruption step (attempt {_passkey_attempt_count}/{_MAX_PASSKEY_ATTEMPTS})")

    try:
        # ------------------------------------------------------------------ #
        # LOOP GUARD — If we've been here too many times, just navigate away  #
        # ------------------------------------------------------------------ #
        if _passkey_attempt_count > _MAX_PASSKEY_ATTEMPTS:
            logger.warning(
                f"⚠️ Passkey loop detected ({_passkey_attempt_count} attempts) — "
                f"forcing navigation away"
            )
            _passkey_attempt_count = 0
            return _navigate_away_from_passkey(page)

        # ------------------------------------------------------------------ #
        # Step 0 — Try pre-emptive WebAuthn bypass (sets up if not already)   #
        # ------------------------------------------------------------------ #
        if not getattr(page, '_webauthn_cdp', None):
            logger.info("🔐 Setting up WebAuthn bypass (late initialization)...")
            setup_webauthn_bypass(page)
            # Give page time to react to the virtual authenticator
            time.sleep(2)
            # Check if the dialog already dismissed itself
            if _is_popup_dismissed(page):
                logger.success("✅ WebAuthn bypass dismissed the dialog")
                _passkey_attempt_count = 0
                return _handle_post_dismiss(page, device)

        # ------------------------------------------------------------------ #
        # Step 1 — Dismiss the native passkey dialog via CDP + OS-level ESC   #
        # ------------------------------------------------------------------ #
        popup_dismissed = _dismiss_native_passkey_dialog(page)

        if popup_dismissed:
            logger.success("✅ Native passkey popup dismissed")
            _passkey_attempt_count = 0
        else:
            logger.warning("⚠️  Could not confirm popup dismissal")
            # After 2+ failed attempts, skip straight to navigate-away
            if _passkey_attempt_count >= 2:
                logger.warning("🚀 Repeated failure — navigating away from passkey page")
                _passkey_attempt_count = 0
                return _navigate_away_from_passkey(page)

        # ------------------------------------------------------------------ #
        # Step 2 — Wait for the "We couldn't create a passkey" error page     #
        #          then click Cancel                                           #
        # ------------------------------------------------------------------ #
        logger.info("⏳ Waiting for passkey error page...")
        if _wait_for_error_page(page, timeout=6):
            logger.info("🔍 Passkey error page detected — clicking Cancel")
            if _click_cancel_on_error_page(page, device):
                logger.success("✅ Clicked Cancel on passkey error page")
                _passkey_attempt_count = 0
                return True
            logger.warning("⚠️  Error page found but could not click Cancel — trying fallbacks")

        # ------------------------------------------------------------------ #
        # Step 3 — Fallback chain (skip / cancel via various strategies)      #
        # ------------------------------------------------------------------ #

        # Fallback 0: Cached XPaths
        try:
            if _handle_via_cache(page, device):
                logger.success("✅ PASSKEY step completed via cached selectors")
                return True
        except Exception as e:
            logger.debug(f"Cached selector approach failed: {e}")

        # Fallback 1: CSS selectors
        try:
            if _handle_via_selectors(page, device):
                return True
        except Exception as e:
            logger.debug(f"CSS selector approach failed: {e}")

        # Fallback 2: AgentQL
        if agentql_page:
            try:
                if _handle_via_agentql(page, agentql_page, device):
                    return True
            except Exception as e:
                logger.warning(f"AgentQL approach failed: {e}")

        # Fallback 3: get_by_role
        try:
            if _handle_via_role(page, device):
                return True
        except Exception as e:
            logger.debug(f"get_by_role failed: {e}")

        # Fallback 4 (nuclear): Navigate away from fido/passkey page
        logger.warning("All passkey dismissal methods failed — navigating away")
        _passkey_attempt_count = 0
        return _navigate_away_from_passkey(page)

    except Exception as e:
        logger.error(f"Passkey handling failed: {e}")
        _passkey_attempt_count = 0
        return False


# ---------------------------------------------------------------------------
# Tier 0: Cached XPaths
# ---------------------------------------------------------------------------

def _handle_via_cache(page, device) -> bool:
    """Try using cached XPaths from previous successful runs."""
    # Try skip button first (preferred)
    skip_el = find_element(page, "passkey_skip_button", timeout=2000)
    if skip_el:
        logger.info("✅ Found Skip button via cache")
        device.tap(skip_el, description="Skip for now (cached)")
        return _wait_for_navigation(page)

    # Try cancel button — but VERIFY it's actually "Cancel", not "Try again"
    cancel_el = find_element(page, "passkey_cancel_button", timeout=1500)
    if cancel_el:
        try:
            btn_text = cancel_el.inner_text(timeout=500).strip().lower()
            if "try again" in btn_text:
                logger.warning("⚠️ Cached cancel button matched 'Try again' — skipping cache")
                return False
        except Exception:
            pass  # Can't verify text, proceed
        logger.info("✅ Found Cancel button via cache")
        device.tap(cancel_el, description="Cancel (cached)")
        return _wait_for_navigation(page)

    return False


# ---------------------------------------------------------------------------
# Tier 1: CSS Selectors
# ---------------------------------------------------------------------------

def _handle_via_selectors(page, device) -> bool:
    """Handle passkey step using CSS selectors."""
    logger.info("🔍 Attempting PASSKEY via CSS selectors...")

    # Skip buttons (preferred)
    skip_selectors = [
        "button:has-text('Skip for now')",
        "a:has-text('Skip for now')",
        "button:has-text('Skip')",
        "[data-testid='skip-passkey']",
    ]

    for selector in skip_selectors:
        try:
            btn = page.locator(selector).first
            if btn.is_visible(timeout=1000):
                logger.info(f"✅ Found Skip button with: {selector}")
                device.tap(btn, description="Skip for now Button")
                return _wait_for_navigation(page)
        except Exception:
            pass

    # Cancel buttons (fallback) — Microsoft auth pages use <input> not <button>
    # CRITICAL: Never match "Try again" — only target actual Cancel buttons
    cancel_selectors = [
        "input[value='Cancel']",          # Microsoft <input type="button" value="Cancel">
        "input[value='cancel']",
        "button:has-text('Cancel')",
        "button[id*='cancel']",
        "a:has-text('Cancel')",
    ]

    for selector in cancel_selectors:
        try:
            btn = page.locator(selector).first
            if btn.is_visible(timeout=1000):
                # Verify we're not accidentally matching "Try again"
                try:
                    btn_text = btn.inner_text(timeout=500).strip().lower()
                    if "try again" in btn_text:
                        logger.warning(f"⚠️ Selector {selector} matched 'Try again' — skipping")
                        continue
                except Exception:
                    pass
                logger.info(f"✅ Found Cancel button with: {selector}")
                device.tap(btn, description="Passkey Cancel Button")
                return _wait_for_navigation(page)
        except Exception:
            pass

    # Last CSS resort: get_by_role matches <input type="button"> by accessible name
    try:
        cancel_btn = page.get_by_role("button", name="Cancel")
        if cancel_btn.is_visible(timeout=1000):
            logger.info("✅ Found Cancel button via get_by_role")
            device.tap(cancel_btn, description="Passkey Cancel Button (role)")
            return _wait_for_navigation(page)
    except Exception:
        pass

    return False


# ---------------------------------------------------------------------------
# Tier 2: AgentQL fallback (extracts & caches XPaths)
# ---------------------------------------------------------------------------

def _handle_via_agentql(page, agentql_page, device) -> bool:
    """Handle passkey step using AgentQL with XPath extraction and caching."""
    import agentql

    logger.info("🧠 Attempting AgentQL fallback for PASSKEY...")

    aq_page = agentql_page if agentql_page else agentql.wrap(page)
    response = aq_page.query_elements(PASSKEY_STEP_QUERY)

    # Try skip button first
    if response.skip_button:
        # Cache XPath for future fast lookups
        if DOMPATH_AVAILABLE:
            try:
                extract_and_cache_xpath(
                    response.skip_button, "passkey_skip_button", {"step": "passkey"}
                )
            except Exception as e:
                logger.debug(f"XPath extraction for skip failed: {e}")

        logger.info("✅ Found Skip button via AgentQL")
        device.tap(response.skip_button, description="Skip for now (AgentQL)")
        return _wait_for_navigation(page)

    # Try cancel button
    if response.cancel_button:
        if DOMPATH_AVAILABLE:
            try:
                extract_and_cache_xpath(
                    response.cancel_button, "passkey_cancel_button", {"step": "passkey"}
                )
            except Exception as e:
                logger.debug(f"XPath extraction for cancel failed: {e}")

        logger.info("✅ Found Cancel button via AgentQL")
        device.tap(response.cancel_button, description="Cancel (AgentQL)")
        return _wait_for_navigation(page)

    logger.warning("AgentQL could not find Skip or Cancel button")
    return False


# ---------------------------------------------------------------------------
# Tier 3: get_by_role (last resort)
# ---------------------------------------------------------------------------

def _handle_via_role(page, device) -> bool:
    """Try using semantic get_by_role as a last resort."""
    logger.info("Trying get_by_role for buttons...")

    try:
        skip_btn = page.get_by_role("button", name="Skip for now")
        if skip_btn.is_visible(timeout=500):
            device.tap(skip_btn, description="Skip Button (role)")
            time.sleep(2)
            return True
    except Exception:
        pass

    # Explicitly avoid "Try again" — only target "Cancel"
    try:
        cancel_btn = page.get_by_role("button", name="Cancel")
        if cancel_btn.is_visible(timeout=500):
            device.tap(cancel_btn, description="Cancel Button (role)")
            time.sleep(2)
            return True
    except Exception:
        pass

    return False


# ---------------------------------------------------------------------------
# Native passkey dialog dismissal (CDP + OS-level + page ESC)
# ---------------------------------------------------------------------------

def _dismiss_native_passkey_dialog(page) -> bool:
    """
    Dismiss the native passkey/Touch ID/Windows Hello dialog.

    The native dialog is an OS-level popup that CANNOT be reached by
    Playwright's page.keyboard.press("Escape") — those keys go to the
    webpage, not the system dialog.

    Strategy (in order):
      1. CDP WebAuthn: Enable virtual authenticator to cancel the WebAuthn ceremony
      2. OS-level Escape: Send ESC via osascript (macOS) or similar
      3. Page-level ESC: As a fallback for browser-level (non-native) dialogs
      4. Verify: Check if the error page / skip button appeared
    """
    logger.info("🔐 Attempting to dismiss native passkey dialog...")

    # ── Strategy 1: CDP WebAuthn — Cancel the credential creation ────────
    cdp_dismissed = _cancel_via_cdp_webauthn(page)
    if cdp_dismissed:
        time.sleep(1.5)  # Give page time to react to cancelled ceremony
        if _is_popup_dismissed(page):
            logger.success("✅ Native dialog cancelled via CDP WebAuthn")
            return True

    # ── Strategy 2: OS-level Escape (macOS: osascript, etc.) ─────────────
    os_dismissed = _send_os_level_escape()
    if os_dismissed:
        time.sleep(1.5)
        if _is_popup_dismissed(page):
            logger.success("✅ Native dialog dismissed via OS-level Escape")
            return True

    # ── Strategy 3: Page-level ESC (works for browser-level dialogs) ─────
    logger.info("⌨️  Trying page-level ESC as fallback...")
    for round_num in range(1, _ESC_MAX_ROUNDS + 1):
        for _ in range(3):
            page.keyboard.press("Escape")
            time.sleep(0.3)
        time.sleep(_ESC_CHECK_INTERVAL)

        logger.debug(f"  ESC round {round_num}/{_ESC_MAX_ROUNDS} — checking state...")
        if _is_popup_dismissed(page):
            logger.success(f"✅ Dialog dismissed via page ESC (round {round_num})")
            return True

    logger.warning("⚠️  Could not dismiss native passkey dialog via any method")
    return False


def _cancel_via_cdp_webauthn(page) -> bool:
    """
    Use Chrome DevTools Protocol to cancel the WebAuthn credential creation.

    By enabling WebAuthn with a virtual authenticator, we force the browser
    to use the virtual authenticator instead of the native one. This cancels
    any pending native dialog. Then we remove the virtual authenticator,
    which fails the ceremony and triggers the error page.
    """
    cdp = None
    try:
        cdp = page.context.new_cdp_session(page)

        # Enable the WebAuthn domain
        cdp.send("WebAuthn.enable", {"enableUI": False})
        logger.debug("  CDP: WebAuthn.enable sent")

        # Add a virtual authenticator (this intercepts the pending credential request)
        result = cdp.send("WebAuthn.addVirtualAuthenticator", {
            "options": {
                "protocol": "ctap2",
                "transport": "internal",
                "hasResidentKey": True,
                "hasUserVerification": True,
                "isUserVerified": False,  # Simulate user declining
                "automaticPresenceSimulation": False,
            }
        })
        authenticator_id = result.get("authenticatorId")
        logger.debug(f"  CDP: Virtual authenticator added: {authenticator_id}")

        # Brief pause to let the browser process the authenticator
        time.sleep(1.0)

        # Remove the authenticator — this causes the WebAuthn ceremony to fail
        if authenticator_id:
            try:
                cdp.send("WebAuthn.removeVirtualAuthenticator", {
                    "authenticatorId": authenticator_id
                })
                logger.debug("  CDP: Virtual authenticator removed")
            except Exception:
                pass

        # Disable WebAuthn domain
        try:
            cdp.send("WebAuthn.disable")
        except Exception:
            pass

        cdp.detach()
        logger.info("  CDP: WebAuthn ceremony cancelled successfully")
        return True

    except Exception as e:
        logger.debug(f"  CDP WebAuthn cancel failed: {e}")
        if cdp:
            try:
                cdp.detach()
            except Exception:
                pass
        return False


def _send_os_level_escape() -> bool:
    """
    Send Escape key at the OS level to dismiss native system dialogs.
    Uses osascript on macOS. On other platforms, skips gracefully.
    """
    if platform.system() != "Darwin":
        logger.debug("  OS-level ESC: Not macOS, skipping")
        return False

    try:
        logger.info("  🍎 Sending OS-level Escape via osascript...")
        # Send multiple Escape presses — one for the Touch ID dialog, one for any
        # intermediate "Choose where to save" selector
        for i in range(3):
            subprocess.run(
                ["osascript", "-e",
                 'tell application "System Events" to key code 53'],
                timeout=3,
                capture_output=True,
            )
            time.sleep(0.5)
        logger.info("  ✅ OS-level Escape sent successfully")
        return True
    except subprocess.TimeoutExpired:
        logger.warning("  osascript timed out")
        return False
    except FileNotFoundError:
        logger.debug("  osascript not found")
        return False
    except Exception as e:
        logger.debug(f"  OS-level Escape failed: {e}")
        return False


def _is_popup_dismissed(page) -> bool:
    """
    Check whether the native passkey dialog has been dismissed.
    Returns True when we can see the error page, skip button, or other
    actionable elements on the page.
    """
    # Check 1: Error heading visible
    try:
        heading = page.locator("h1, h2, [class*='title'], [class*='heading']").first
        text = heading.inner_text(timeout=400)
        if "couldn't create" in text.lower() or "could not create" in text.lower():
            return True
    except Exception:
        pass

    # Check 2: Cancel + Try again buttons visible (error page layout)
    try:
        cancel_visible = page.locator("button:has-text('Cancel')").first.is_visible(timeout=300)
        try_again_visible = page.locator("button:has-text('Try again')").first.is_visible(timeout=300)
        if cancel_visible and try_again_visible:
            return True
    except Exception:
        pass

    # Check 3: Page content indicates error state
    try:
        content = page.content().lower()
        if "couldn't create a passkey" in content or "could not create a passkey" in content:
            return True
    except Exception:
        pass

    # Check 4: Skip button visible
    try:
        skip_visible = page.locator("button:has-text('Skip'), button:has-text('Skip for now')").first.is_visible(timeout=300)
        if skip_visible:
            return True
    except Exception:
        pass

    # Check 5: URL changed away from fido/create (ceremony was cancelled)
    try:
        url = page.url.lower()
        if "fido/create" not in url and "fido/enroll" not in url:
            return True
    except Exception:
        pass

    return False


def _navigate_away_from_passkey(page) -> bool:
    """
    Nuclear fallback: navigate the page away from the passkey/fido URL.

    Playwright's page.goto() uses CDP, which works even when a native OS
    dialog is overlaying the page.  The dialog will close when the page
    navigates.
    """
    try:
        logger.info("🚀 Navigating away from passkey page via page.goto()...")

        # Clean up WebAuthn bypass first — it may interfere with the target page
        cleanup_webauthn_bypass(page)

        # Try multiple destinations in order of preference
        destinations = [
            ("https://outlook.live.com/mail/0/inbox", "Outlook inbox"),
            ("https://account.live.com/", "Microsoft account"),
            ("https://www.microsoft.com/", "Microsoft home"),
        ]

        for url, desc in destinations:
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=15000)
                time.sleep(2)
                current_url = page.url.lower()
                if "fido" not in current_url and "passkey" not in current_url:
                    logger.success(f"✅ Successfully navigated to {desc}")
                    return True
            except Exception as nav_err:
                logger.debug(f"Navigation to {desc} failed: {nav_err}")
                continue

        logger.error("❌ Could not navigate away from passkey page")
        return False
    except Exception as e:
        logger.warning(f"Navigation fallback failed: {e}")
        return False


# ---------------------------------------------------------------------------
# Wait for the "We couldn't create a passkey" error page
# ---------------------------------------------------------------------------

def _wait_for_error_page(page, timeout: int = 8) -> bool:
    """
    Poll for the "We couldn't create a passkey" error page for up to `timeout` seconds.
    Detection is heading-based (not URL-based) because the enrollment URL already
    contains 'passkey'+'enroll' before the popup is dismissed.
    Returns True as soon as we detect we're on the error page.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        # Check 1: Page content contains the error message (most reliable)
        try:
            content = page.content().lower()
            if "couldn't create a passkey" in content or "could not create a passkey" in content:
                logger.debug("Error page detected via page content")
                return True
        except Exception:
            pass

        # Check 2: Visible heading contains the error message
        try:
            heading = page.locator("h1, h2, [class*='title'], [class*='heading']").first
            text = heading.inner_text(timeout=400)
            if "couldn't create" in text.lower() or "could not create" in text.lower():
                logger.debug("Error page detected via heading text")
                return True
        except Exception:
            pass

        # Check 3: A visible Cancel button exists alongside a Try again button (error page layout)
        try:
            cancel_btn = page.locator("button:has-text('Cancel')").first
            try_again_btn = page.locator("button:has-text('Try again')").first
            if cancel_btn.is_visible(timeout=300) and try_again_btn.is_visible(timeout=300):
                logger.debug("Error page detected via Cancel + Try again buttons")
                return True
        except Exception:
            pass

        # Check 4: known XPath for Cancel button (legacy — kept as last resort)
        try:
            cancel_btn = page.locator("xpath=//*[@id='view']/div/div[5]/button[2]")
            if cancel_btn.is_visible(timeout=400):
                logger.debug("Error page detected via XPath button[2]")
                return True
        except Exception:
            pass

        time.sleep(0.4)
    return False


# ---------------------------------------------------------------------------
# Click Cancel on the error page
# ---------------------------------------------------------------------------

def _click_cancel_on_error_page(page, device) -> bool:
    """
    Click the Cancel button on the "We couldn't create a passkey" error page.
    CRITICAL: Must click Cancel, NOT "Try again". Clicking "Try again" loops
    back to the passkey creation prompt and gets stuck.
    """
    # ── Priority 1: Text-based selectors (most reliable across devices) ─────
    # Explicitly match "Cancel" by text — this is layout-independent.
    for selector in [
        "button:has-text('Cancel')",
        "input[value='Cancel']",
        "input[value='cancel']",
        "a:has-text('Cancel')",
    ]:
        try:
            btn = page.locator(selector).first
            if btn.is_visible(timeout=1500):
                # Verify it's NOT the "Try again" button (paranoid check)
                try:
                    btn_text = btn.inner_text(timeout=500).strip().lower()
                    if "try again" in btn_text:
                        logger.warning(f"  ⚠️ Selector {selector} matched 'Try again' — skipping")
                        continue
                except Exception:
                    pass
                logger.info(f"  ✅ Cancel via selector: {selector}")
                device.tap(btn, description="Cancel on passkey error page")
                return True
        except Exception:
            pass

    # ── Priority 2: Accessible role ─────────────────────────────────────────
    try:
        btn = page.get_by_role("button", name="Cancel", exact=True)
        if btn.is_visible(timeout=1000):
            logger.info("  ✅ Cancel via get_by_role (exact)")
            device.tap(btn, description="Cancel on passkey error page (role)")
            return True
    except Exception:
        pass

    # ── Priority 3: JS-based click — explicitly finds Cancel, ignores Try again
    try:
        result = page.evaluate("""
            () => {
                const buttons = Array.from(document.querySelectorAll('button, input[type="button"], input[type="submit"], a'));
                const cancelBtn = buttons.find(el => {
                    const text = (el.textContent || el.value || '').trim().toLowerCase();
                    return text === 'cancel' && !text.includes('try again');
                });
                if (cancelBtn) {
                    cancelBtn.click();
                    return 'clicked_cancel';
                }
                return null;
            }
        """)
        if result:
            logger.info(f"  ✅ Cancel via JS evaluate: {result}")
            return True
    except Exception as e:
        logger.debug(f"JS cancel click failed: {e}")

    # ── Priority 4: Positional XPath (last resort, fragile) ────────────────
    try:
        btn = page.locator("xpath=//*[@id='view']/div/div[5]/button[2]")
        if btn.is_visible(timeout=1000):
            # Verify button text to make sure it's Cancel, not Try again
            try:
                btn_text = btn.inner_text(timeout=500).strip().lower()
                if "try again" in btn_text:
                    logger.warning("  ⚠️ XPath button[2] matched 'Try again' — skipping")
                else:
                    logger.info("  ✅ Cancel via XPath (button[2]) — verified text")
                    device.tap(btn, description="Cancel on passkey error page (XPath)")
                    return True
            except Exception:
                # Can't verify text, try anyway as last resort
                logger.info("  ✅ Cancel via XPath (button[2]) — unverified")
                device.tap(btn, description="Cancel on passkey error page (XPath)")
                return True
    except Exception:
        pass

    return False


# ---------------------------------------------------------------------------
# Special: "We couldn't create a passkey" error page (kept for fallback chain)
# ---------------------------------------------------------------------------

def _handle_passkey_error_page(page, device) -> bool:
    """Legacy wrapper — used by fallback chain."""
    if _wait_for_error_page(page, timeout=2):
        return _click_cancel_on_error_page(page, device)
    return False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _handle_post_dismiss(page, device) -> bool:
    """
    After the native dialog is dismissed, handle the resulting error page
    or navigate away if needed.
    """
    # Wait briefly for the error page to appear
    if _wait_for_error_page(page, timeout=4):
        if _click_cancel_on_error_page(page, device):
            logger.success("✅ Clicked Cancel on post-dismiss error page")
            return True
    # If no error page appeared, check if we've already navigated away
    url = page.url.lower()
    if "fido/create" not in url and "fido/enroll" not in url:
        logger.success("✅ Already navigated away from passkey page")
        return True
    # Still stuck — navigate away
    return _navigate_away_from_passkey(page)


def _wait_for_navigation(page, timeout: int = 10000) -> bool:
    """Wait for the page to navigate away from the passkey/interruption step."""
    try:
        page.wait_for_url(
            lambda u: (
                "interruption" not in u.lower()
                and "passkey" not in u.lower()
                and "fido/create" not in u.lower()
                and "fido/enroll" not in u.lower()
            ),
            timeout=timeout,
        )
        logger.success("✅ Successfully skipped passkey setup")
        return True
    except Exception:
        # Check if we're actually still stuck on the passkey page
        try:
            url = page.url.lower()
            if any(p in url for p in ("fido/create", "fido/enroll", "passkey", "interruption")):
                logger.warning("⚠️ Still on passkey page after timeout — navigation did NOT happen")
                return False
        except Exception:
            pass
        logger.info("Navigation may have happened, continuing...")
        time.sleep(1)
        return True
