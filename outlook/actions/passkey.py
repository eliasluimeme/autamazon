"""
Passkey / Interruption Step Handler

Handles the passkey setup interruption from Microsoft during Outlook signup.

Flow:
  1. Press ESC to dismiss the native browser/OS passkey popup (with retry verification)
  2. Wait for Microsoft to redirect to the "We couldn't create a passkey" error page
  3. Click "Cancel" on that error page (NOT "Try again")

Fallback chain (if ESC + error-page cancel doesn't apply):
  1. Cached XPath selectors  (fastest)
  2. CSS selectors            (fast)
  3. AgentQL fallback         (slow but robust)
  4. get_by_role              (last resort)
"""

import time
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


def handle_passkey_step(page, device, agentql_page=None) -> bool:
    """
    Handle the Passkey Setup interruption.

    Expected sequence:
      native popup visible  →  ESC keypresses  →  "We couldn't create a passkey" error page
                                                →  click Cancel  →  proceed
    """
    logger.info("🚫 Handling Passkey/Interruption step")

    try:
        # ------------------------------------------------------------------ #
        # Step 1 — Dismiss the native browser/OS passkey popup via ESC        #
        # ------------------------------------------------------------------ #
        popup_dismissed = _dismiss_popup_with_esc(page)

        if popup_dismissed:
            logger.success("✅ Native passkey popup dismissed via ESC")
        else:
            logger.warning("⚠️  Could not confirm popup dismissal — continuing anyway")

        # ------------------------------------------------------------------ #
        # Step 2 — Wait for the "We couldn't create a passkey" error page     #
        #          then click Cancel                                           #
        # ------------------------------------------------------------------ #
        logger.info("⏳ Waiting for passkey error page after ESC...")
        if _wait_for_error_page(page, timeout=5):
            logger.info("🔍 Passkey error page detected — clicking Cancel")
            if _click_cancel_on_error_page(page, device):
                logger.success("✅ Clicked Cancel on passkey error page")
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

        logger.warning("Could not find Skip or Cancel button for passkey step")
        return False

    except Exception as e:
        logger.error(f"Passkey handling failed: {e}")
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

    # Try cancel button
    cancel_el = find_element(page, "passkey_cancel_button", timeout=1500)
    if cancel_el:
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
# ESC dismissal with retry verification
# ---------------------------------------------------------------------------

def _dismiss_popup_with_esc(page) -> bool:
    """
    Press ESC repeatedly and verify the native passkey popup has been dismissed.

    Strategy:
      - Round 1-N: press ESC 2×, wait, check if a dialog/popup is still overlaying the page.
      - We consider the popup gone when:
          a) No [role=dialog] / [role=alertdialog] is visible on the page, OR
          b) The page URL has changed to include 'passkey' or 'interrupt' (error redirect), OR
          c) A Cancel / Skip button is now visible in the page DOM.
      - After _ESC_MAX_ROUNDS with no confirmation we still return False but have
        pressed ESC a total of (rounds × 2) times.
    """
    logger.info(f"⌨️  Pressing ESC to dismiss native passkey popup (max {_ESC_MAX_ROUNDS} rounds)...")

    for round_num in range(1, _ESC_MAX_ROUNDS + 1):
        # Two ESC presses per round — some OS dialogs need multiple
        page.keyboard.press("Escape")
        time.sleep(0.3)
        page.keyboard.press("Escape")
        time.sleep(_ESC_CHECK_INTERVAL)

        logger.debug(f"  ESC round {round_num}/{_ESC_MAX_ROUNDS} — checking popup state...")

        # Check 1: Error page heading appeared — means popup was dismissed and page redirected
        try:
            heading = page.locator("h1, h2, [class*='title'], [class*='heading']").first
            text = heading.inner_text(timeout=400)
            if "couldn't create" in text.lower() or "could not create" in text.lower():
                logger.info(f"  ✅ Round {round_num}: Error page heading detected — popup dismissed")
                return True
        except Exception:
            pass

        # Check 2: No visible dialog overlay remaining
        try:
            dialog_visible = page.locator("[role='dialog'], [role='alertdialog']").first.is_visible(timeout=300)
            if not dialog_visible:
                logger.info(f"  ✅ Round {round_num}: No dialog overlay detected — popup dismissed")
                return True
        except Exception:
            # Timeout / not found = popup is gone
            logger.info(f"  ✅ Round {round_num}: Dialog locator timed out — popup likely gone")
            return True

        # Check 3: The known Cancel button (second button in #view) is now visible
        try:
            cancel_btn = page.locator("xpath=//*[@id='view']/div/div[5]/button[2]")
            if cancel_btn.is_visible(timeout=300):
                logger.info(f"  ✅ Round {round_num}: Cancel button visible via XPath — popup dismissed")
                return True
        except Exception:
            pass

        logger.debug(f"  ⟳  Round {round_num}: popup may still be active, retrying ESC...")

    logger.warning(f"⚠️  Popup not confirmed dismissed after {_ESC_MAX_ROUNDS} ESC rounds")
    return False


# ---------------------------------------------------------------------------
# Wait for the "We couldn't create a passkey" error page
# ---------------------------------------------------------------------------

def _wait_for_error_page(page, timeout: int = 6) -> bool:
    """
    Poll for the "We couldn't create a passkey" error page for up to `timeout` seconds.
    Detection is heading-based (not URL-based) because the enrollment URL already
    contains 'passkey'+'enroll' before the popup is dismissed.
    Returns True as soon as we detect we're on the error page.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            # Primary: known XPath for Cancel button only appears on the error page
            cancel_btn = page.locator("xpath=//*[@id='view']/div/div[5]/button[2]")
            if cancel_btn.is_visible(timeout=400):
                return True
        except Exception:
            pass

        try:
            # Secondary: page heading contains the error message
            heading = page.locator("h1, h2, [class*='title'], [class*='heading']").first
            text = heading.inner_text(timeout=400)
            if "couldn't create" in text.lower() or "could not create" in text.lower():
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
    Cancel is the SECOND button; Try again is the FIRST. Never target button[1].
    """
    # ── Priority 1: Direct XPath (most reliable — Cancel is button[2]) ──────
    try:
        btn = page.locator("xpath=//*[@id='view']/div/div[5]/button[2]")
        if btn.is_visible(timeout=1500):
            logger.info("  ✅ Cancel via known XPath (button[2])")
            device.tap(btn, description="Cancel on passkey error page (XPath)")
            return True
    except Exception:
        pass

    # ── Priority 2: Second button inside #view (nth-based, avoids Try again) ─
    try:
        btn = page.locator("#view button").nth(1)   # 0-indexed → second button = Cancel
        if btn.is_visible(timeout=1000):
            logger.info("  ✅ Cancel via #view button nth(1)")
            device.tap(btn, description="Cancel on passkey error page (nth)")
            return True
    except Exception:
        pass

    # ── Priority 3: Text-based selectors ────────────────────────────────────
    for selector in [
        "input[value='Cancel']",
        "input[value='cancel']",
        "button:has-text('Cancel')",
        "a:has-text('Cancel')",
    ]:
        try:
            btn = page.locator(selector).first
            if btn.is_visible(timeout=1000):
                logger.info(f"  ✅ Cancel via selector: {selector}")
                device.tap(btn, description="Cancel on passkey error page")
                return True
        except Exception:
            pass

    # ── Priority 4: Accessible role ─────────────────────────────────────────
    try:
        btn = page.get_by_role("button", name="Cancel")
        if btn.is_visible(timeout=1000):
            logger.info("  ✅ Cancel via get_by_role")
            device.tap(btn, description="Cancel on passkey error page (role)")
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

def _wait_for_navigation(page, timeout: int = 10000) -> bool:
    """Wait for the page to navigate away from the passkey/interruption step."""
    try:
        page.wait_for_url(
            lambda u: "interruption" not in u.lower() and "passkey" not in u.lower(),
            timeout=timeout,
        )
        logger.success("✅ Successfully skipped passkey setup")
        return True
    except Exception:
        logger.info("Navigation may have happened, continuing...")
        time.sleep(1)
        return True
