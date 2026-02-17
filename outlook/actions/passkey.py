"""
Passkey / Interruption Step Handler

Handles the "We couldn't create a passkey" or "Setting up your passkey" interruption.

Strategy (3-tier):
  1. Cached XPath selectors  (fastest — from data/xpath_cache/outlook_selectors.json)
  2. CSS selectors            (fast — browser-native querySelector)
  3. AgentQL fallback          (slow but robust — extracts & caches XPaths for next run)

Fallback:
  - Press Escape multiple times (to dismiss native/browser popups)
  - Click "Skip for now" button if available (preferred)
  - Fall back to "Cancel" button on the page
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


def handle_passkey_step(page, device, agentql_page=None) -> bool:
    """
    Handle the Passkey Setup interruption.

    The user sees system dialogs like "Use Touch ID" or "Choose where to save".
    We need to dismiss them via keyboard and then skip/cancel the process on the page.
    """
    logger.info("🚫 Handling Passkey/Interruption step")

    try:
        # 1. Press ESC multiple times to dismiss system/browser dialogs
        logger.info("⌨️ Pressing ESC x3 to dismiss dialogs...")
        for _ in range(3):
            page.keyboard.press("Escape")
            time.sleep(0.5)
        time.sleep(0.5)

        # Priority 0: Try cached selectors (self-healing)
        try:
            success = _handle_via_cache(page, device)
            if success:
                logger.success("✅ PASSKEY step completed via cached selectors")
                return True
        except Exception as e:
            logger.debug(f"Cached selector approach failed: {e}")

        # Priority 1: Try CSS selectors
        try:
            success = _handle_via_selectors(page, device)
            if success:
                return True
        except Exception as e:
            logger.debug(f"CSS selector approach failed: {e}")

        # Priority 2: AgentQL fallback with XPath extraction
        if agentql_page:
            try:
                success = _handle_via_agentql(page, agentql_page, device)
                if success:
                    return True
            except Exception as e:
                logger.warning(f"AgentQL approach failed: {e}")

        # Priority 3: get_by_role (last resort)
        try:
            success = _handle_via_role(page, device)
            if success:
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

    # Cancel buttons (fallback)
    cancel_selectors = [
        "button:has-text('Cancel')",
        "#idBtn_Back",
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
