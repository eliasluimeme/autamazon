"""
Privacy Notice Step Handler for Outlook Signup

Handles the privacy notice page that appears after CAPTCHA.
Simply clicks the "OK" button to proceed.

Strategy (3-tier):
  1. Cached XPath selectors  (fastest — from data/xpath_cache/outlook_selectors.json)
  2. CSS selectors            (fast — browser-native querySelector)
  3. AgentQL fallback          (slow but robust — extracts & caches XPaths for next run)
"""

import time
import random
from loguru import logger

from amazon.outlook.queries import PRIVACY_STEP_QUERY
from amazon.outlook.utils.xpath_cache import (
    find_element,
    extract_and_cache_xpath,
    get_cached_xpath,
    DOMPATH_AVAILABLE,
)


def handle_privacy_step(page, device, agentql_page=None) -> bool:
    """
    Handle the privacy notice step by clicking OK.

    Args:
        page: Playwright page
        device: DeviceAdapter instance
        agentql_page: Optional AgentQL-wrapped page

    Returns:
        True if step completed successfully
    """
    logger.info("📋 Handling Privacy Notice step")

    # Priority 0: Try cached selectors (self-healing)
    try:
        success = _handle_via_cache(page, device)
        if success:
            logger.success("✅ PRIVACY step completed via cached selectors")
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
            logger.warning(f"AgentQL privacy notice failed: {e}")

    logger.error("Could not find OK button on privacy notice")
    return False


# ---------------------------------------------------------------------------
# Tier 0: Cached XPaths
# ---------------------------------------------------------------------------

def _handle_via_cache(page, device) -> bool:
    """Try using cached XPaths from previous successful runs."""
    # Try OK button
    ok_el = find_element(page, "privacy_ok_button", timeout=2000)
    if ok_el:
        logger.info("✅ Found OK button via cache")
        device.js_click(ok_el, "OK button (cached)")
        time.sleep(2)
        return True

    # Try accept button
    accept_el = find_element(page, "privacy_accept_button", timeout=1500)
    if accept_el:
        logger.info("✅ Found Accept button via cache")
        device.js_click(accept_el, "Accept button (cached)")
        time.sleep(2)
        return True

    return False


# ---------------------------------------------------------------------------
# Tier 1: CSS Selectors
# ---------------------------------------------------------------------------

def _handle_via_selectors(page, device) -> bool:
    """Handle privacy step using CSS selectors."""
    logger.info("🔍 Attempting PRIVACY via CSS selectors...")

    ok_button_selectors = [
        "button:has-text('OK')",
        "button:has-text('Ok')",
        "button#acceptButton",
        "button[id*='accept']",
        "button[id*='Accept']",
        "input[value='OK']",
        "button[type='submit']",
        "#idBtn_Accept",
        ".btn-primary:has-text('OK')",
    ]

    for selector in ok_button_selectors:
        try:
            btn = page.locator(selector).first
            if btn.is_visible(timeout=2000):
                logger.debug(f"Found OK button with: {selector}")
                if device.js_click(btn, "OK button"):
                    time.sleep(2)
                    logger.success("✅ Clicked OK on privacy notice")
                    return True
                else:
                    logger.warning(f"Tap failed for {selector}, retrying...")
        except Exception as e:
            logger.debug(f"Selector {selector} failed: {e}")
            continue

    return False


# ---------------------------------------------------------------------------
# Tier 2: AgentQL fallback (extracts & caches XPaths)
# ---------------------------------------------------------------------------

def _handle_via_agentql(page, agentql_page, device) -> bool:
    """Handle privacy step using AgentQL with XPath extraction and caching."""
    import agentql

    logger.info("🧠 Attempting AgentQL fallback for PRIVACY...")

    aq_page = agentql_page if agentql_page else agentql.wrap(page)
    response = aq_page.query_elements(PRIVACY_STEP_QUERY)

    if response.ok_button:
        # Extract and cache XPath for future use
        if DOMPATH_AVAILABLE:
            try:
                extract_and_cache_xpath(
                    response.ok_button, "privacy_ok_button", {"step": "privacy"}
                )
            except Exception as e:
                logger.debug(f"XPath extraction failed: {e}")

        logger.debug("Found OK button via AgentQL")
        device.js_click(response.ok_button, "OK button (AgentQL)")
        time.sleep(2)
        logger.success("✅ Clicked OK on privacy notice (AgentQL)")
        return True

    elif response.accept_button:
        if DOMPATH_AVAILABLE:
            try:
                extract_and_cache_xpath(
                    response.accept_button, "privacy_accept_button", {"step": "privacy"}
                )
            except Exception as e:
                logger.debug(f"XPath extraction failed: {e}")

        logger.debug("Found accept button via AgentQL")
        device.js_click(response.accept_button, "accept button (AgentQL)")
        time.sleep(2)
        return True

    logger.warning("AgentQL could not find OK or accept button")
    return False
