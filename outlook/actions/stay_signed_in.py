"""
Stay Signed In Step Handler for Outlook Signup

Handles the "Stay signed in?" prompt by clicking Yes.

Strategy (3-tier):
  1. Cached XPath selectors  (fastest — from data/xpath_cache/outlook_selectors.json)
  2. CSS selectors            (fast — browser-native querySelector)
  3. AgentQL fallback          (slow but robust — extracts & caches XPaths for next run)
"""

import time
from loguru import logger

from amazon.outlook.queries import STAY_SIGNED_IN_QUERY
from amazon.outlook.utils.xpath_cache import (
    find_element,
    extract_and_cache_xpath,
    get_cached_xpath,
    DOMPATH_AVAILABLE,
)


def handle_stay_signed_in_step(page, device, agentql_page=None) -> bool:
    """
    Handle the "Stay signed in?" prompt by clicking Yes.

    Args:
        page: Playwright page
        device: DeviceAdapter instance
        agentql_page: Optional AgentQL-wrapped page

    Returns:
        True if step completed successfully
    """
    logger.info("✅ Handling 'Stay signed in?' step")

    # Priority 0: Try cached selectors (self-healing)
    try:
        success = _handle_via_cache(page, device)
        if success:
            logger.success("✅ STAY_SIGNED_IN step completed via cached selectors")
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
        yes_btn = page.get_by_role("button", name="Yes")
        if yes_btn.is_visible(timeout=1000):
            device.js_click(yes_btn, "Yes button (role)")
            time.sleep(2)
            logger.success("✅ Clicked Yes via get_by_role")
            return True
    except Exception:
        pass

    logger.error("Could not find Yes button on 'Stay signed in?' prompt")
    return False


# ---------------------------------------------------------------------------
# Tier 0: Cached XPaths
# ---------------------------------------------------------------------------

def _handle_via_cache(page, device) -> bool:
    """Try using cached XPaths from previous successful runs."""
    yes_el = find_element(page, "stay_signed_in_yes", timeout=2000)
    if yes_el:
        logger.info("✅ Found Yes button via cache")
        device.js_click(yes_el, "Yes button (cached)")
        time.sleep(2)
        logger.success("✅ Clicked Yes on 'Stay signed in?' (cached)")
        return True

    return False


# ---------------------------------------------------------------------------
# Tier 1: CSS Selectors
# ---------------------------------------------------------------------------

def _handle_via_selectors(page, device) -> bool:
    """Handle stay signed in step using CSS selectors."""
    logger.info("🔍 Attempting STAY_SIGNED_IN via CSS selectors...")

    yes_button_selectors = [
        "#idSIButton9",
        "button:has-text('Yes')",
        "#acceptButton",
        "button[type='submit']",
        "input[value='Yes']",
    ]

    for selector in yes_button_selectors:
        try:
            btn = page.locator(selector).first
            if btn.is_visible(timeout=2000):
                logger.debug(f"Found Yes button with: {selector}")
                device.js_click(btn, "Yes button")
                time.sleep(2)
                logger.success("✅ Clicked Yes on 'Stay signed in?' prompt")
                return True
        except Exception as e:
            logger.debug(f"Selector {selector} failed: {e}")
            continue

    return False


# ---------------------------------------------------------------------------
# Tier 2: AgentQL fallback (extracts & caches XPaths)
# ---------------------------------------------------------------------------

def _handle_via_agentql(page, agentql_page, device) -> bool:
    """Handle stay signed in step using AgentQL with XPath extraction and caching."""
    import agentql

    logger.info("🧠 Attempting AgentQL fallback for STAY_SIGNED_IN...")

    aq_page = agentql_page if agentql_page else agentql.wrap(page)
    response = aq_page.query_elements(STAY_SIGNED_IN_QUERY)

    if response.yes_button:
        # Cache XPath for future fast lookups
        if DOMPATH_AVAILABLE:
            try:
                extract_and_cache_xpath(
                    response.yes_button, "stay_signed_in_yes", {"step": "stay_signed_in"}
                )
            except Exception as e:
                logger.debug(f"XPath extraction for yes_button failed: {e}")

        logger.info("✅ Found Yes button via AgentQL")
        device.js_click(response.yes_button, "Yes button (AgentQL)")
        time.sleep(2)
        logger.success("✅ Clicked Yes on 'Stay signed in?' (AgentQL)")
        return True

    # Also cache no_button if found (for detection purposes)
    if response.no_button:
        if DOMPATH_AVAILABLE:
            try:
                extract_and_cache_xpath(
                    response.no_button, "stay_signed_in_no", {"step": "stay_signed_in"}
                )
            except Exception:
                pass

    logger.warning("AgentQL could not find Yes button")
    return False
