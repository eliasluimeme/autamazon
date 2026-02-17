"""
Password Step Handler for Outlook Signup

Strategy (3-tier):
  1. Cached XPath selectors  (fastest — from data/xpath_cache/outlook_selectors.json)
  2. CSS selectors            (fast — browser-native querySelector)
  3. AgentQL fallback          (slow but robust — extracts & caches XPaths for next run)
"""

import time
import random
from loguru import logger

from amazon.outlook.selectors import SELECTORS
from amazon.outlook.queries import PASSWORD_STEP_QUERY
from amazon.outlook.config import DELAYS
from amazon.outlook.utils.xpath_cache import (
    find_element,
    extract_and_cache_xpath,
    get_cached_xpath,
    DOMPATH_AVAILABLE,
)


def handle_password_step(page, identity: dict, device, agentql_page=None) -> bool:
    """
    Handle the password input step.

    Args:
        page: Playwright page
        identity: Dict with email_handle, password, etc.
        device: DeviceAdapter instance
        agentql_page: Optional AgentQL-wrapped page

    Returns:
        True if step completed successfully
    """
    logger.info("🔐 Handling PASSWORD step")

    # Priority 0: Try cached selectors (self-healing)
    try:
        success = _handle_via_cache(page, identity, device)
        if success:
            logger.success("✅ PASSWORD step completed via cached selectors")
            return True
    except Exception as e:
        logger.debug(f"Cached selector approach failed: {e}")

    # Priority 1: Try CSS selectors
    try:
        success = _handle_via_selectors(page, identity, device)
        if success:
            return True
    except Exception as e:
        logger.debug(f"Selector approach failed: {e}")

    # Priority 2: AgentQL fallback with XPath extraction
    if agentql_page:
        try:
            success = _handle_via_agentql(page, agentql_page, identity, device)
            if success:
                return True
        except Exception as e:
            logger.warning(f"AgentQL approach failed: {e}")

    logger.error("Password step failed with all approaches")
    return False


# ---------------------------------------------------------------------------
# Tier 0: Cached XPaths (via find_element)
# ---------------------------------------------------------------------------

def _handle_via_cache(page, identity: dict, device) -> bool:
    """Try using cached XPaths from previous successful runs."""
    password_el = find_element(page, "password_input", timeout=3000)
    if not password_el:
        logger.debug("Password input not found in cache, skipping cache approach")
        return False

    logger.info("🔄 Attempting PASSWORD via cached selectors...")

    try:
        logger.info("Typing password (cached)...")
        password_el.fill("")
        device.type_text(password_el, identity["password"], "password input (cached)")

        time.sleep(random.uniform(*DELAYS["after_input"]))

        # Click next button (try cache first, then CSS fallback)
        next_btn = find_element(page, "password_next", timeout=2000,
                                css_fallback=SELECTORS["password"]["next_button"])
        if next_btn:
            device.js_click(next_btn, "next button (cached)")
            time.sleep(random.uniform(*DELAYS["step_transition"]))
            return True

    except Exception as e:
        logger.debug(f"Cache approach error: {e}")

    return False


# ---------------------------------------------------------------------------
# Tier 1: CSS Selectors
# ---------------------------------------------------------------------------

def _handle_via_selectors(page, identity: dict, device) -> bool:
    """Handle password step using CSS selectors."""
    logger.info("🔍 Attempting PASSWORD via CSS selectors...")

    password_input = page.locator(SELECTORS["password"]["input"]).first
    if not password_input.is_visible(timeout=3000):
        return False

    logger.info("Typing password...")
    device.type_text(password_input, identity["password"], "password input")

    time.sleep(random.uniform(*DELAYS["after_input"]))

    next_btn = page.locator(SELECTORS["password"]["next_button"]).first
    if next_btn.is_visible(timeout=2000):
        device.js_click(next_btn, "next button")
        time.sleep(random.uniform(*DELAYS["step_transition"]))
        return True

    return False


# ---------------------------------------------------------------------------
# Tier 2: AgentQL fallback (extracts & caches XPaths)
# ---------------------------------------------------------------------------

def _handle_via_agentql(page, agentql_page, identity: dict, device) -> bool:
    """Handle password step using AgentQL with XPath extraction and caching."""
    logger.info("🧠 Attempting AgentQL fallback for PASSWORD...")

    response = agentql_page.query_elements(PASSWORD_STEP_QUERY)

    if not response.password_input:
        logger.warning("AgentQL could not find password input")
        return False

    # Extract and cache XPaths for future use
    if DOMPATH_AVAILABLE:
        try:
            if response.password_input:
                extract_and_cache_xpath(response.password_input, "password_input", {"step": "password"})
            if response.next_button:
                extract_and_cache_xpath(response.next_button, "password_next", {"step": "password"})
        except Exception as e:
            logger.warning(f"XPath extraction failed: {e}")

    logger.info("Typing password (AgentQL)...")
    response.password_input.fill("")
    device.type_text(response.password_input, identity["password"], "password input (AgentQL)")

    time.sleep(random.uniform(*DELAYS["after_input"]))

    if response.next_button:
        device.js_click(response.next_button, "next button (AgentQL)")
        time.sleep(random.uniform(*DELAYS["step_transition"]))
        return True

    return False
