"""
Name Step Handler for Outlook Signup

Strategy (3-tier):
  1. Cached XPath selectors  (fastest — from data/xpath_cache/outlook_selectors.json)
  2. CSS selectors            (fast — browser-native querySelector)
  3. AgentQL fallback          (slow but robust — extracts & caches XPaths for next run)
"""

import time
import random
from loguru import logger

from amazon.outlook.selectors import SELECTORS
from amazon.outlook.queries import NAME_STEP_QUERY
from amazon.outlook.config import DELAYS
from amazon.outlook.utils.xpath_cache import (
    find_element,
    extract_and_cache_xpath,
    get_cached_xpath,
    DOMPATH_AVAILABLE,
)


def handle_name_step(page, identity: dict, device, agentql_page=None) -> bool:
    """
    Handle the name input step.

    Args:
        page: Playwright page
        identity: Dict with firstname, lastname
        device: DeviceAdapter instance
        agentql_page: Optional AgentQL-wrapped page

    Returns:
        True if step completed successfully
    """
    logger.info("👤 Handling NAME step")

    # Priority 0: Try cached selectors (self-healing)
    try:
        success = _handle_via_cache(page, identity, device)
        if success:
            logger.success("✅ NAME step completed via cached selectors")
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

    logger.error("Name step failed with all approaches")
    return False


# ---------------------------------------------------------------------------
# Tier 0: Cached XPaths (via find_element)
# ---------------------------------------------------------------------------

def _handle_via_cache(page, identity: dict, device) -> bool:
    """Try using cached XPaths from previous successful runs."""
    first_name_el = find_element(page, "name_first_name", timeout=3000)
    last_name_el = find_element(page, "name_last_name", timeout=2000)

    if not first_name_el or not last_name_el:
        logger.debug("Not all NAME selectors found in cache, skipping cache approach")
        return False

    logger.info("🔄 Attempting NAME via cached selectors...")

    try:
        logger.info(f"Typing name (cached): {identity['firstname']} {identity['lastname']}")

        # Type first name
        first_name_el.fill("")
        device.type_text(first_name_el, identity["firstname"], "first name (cached)")
        time.sleep(0.2)

        # Type last name
        last_name_el.fill("")
        device.type_text(last_name_el, identity["lastname"], "last name (cached)")

        time.sleep(random.uniform(*DELAYS["after_input"]))

        # Next button (try cache first, then CSS fallback)
        next_btn = find_element(page, "name_next", timeout=2000,
                                css_fallback=SELECTORS["name"]["next_button"])
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
    """Handle name step using CSS selectors."""
    logger.info("🔍 Attempting NAME via CSS selectors...")

    first_name_input = page.locator(SELECTORS["name"]["first_name"]).first
    last_name_input = page.locator(SELECTORS["name"]["last_name"]).first

    if not first_name_input.is_visible(timeout=3000):
        return False

    logger.info(f"Typing name: {identity['firstname']} {identity['lastname']}")

    device.type_text(first_name_input, identity["firstname"], "first name")
    time.sleep(0.2)
    device.type_text(last_name_input, identity["lastname"], "last name")

    time.sleep(random.uniform(*DELAYS["after_input"]))

    next_btn = page.locator(SELECTORS["name"]["next_button"]).first
    if next_btn.is_visible(timeout=2000):
        device.js_click(next_btn, "next button")
        time.sleep(random.uniform(*DELAYS["step_transition"]))
        return True

    return False


# ---------------------------------------------------------------------------
# Tier 2: AgentQL fallback (extracts & caches XPaths)
# ---------------------------------------------------------------------------

def _handle_via_agentql(page, agentql_page, identity: dict, device) -> bool:
    """Handle name step using AgentQL with XPath extraction and caching."""
    logger.info("🧠 Attempting AgentQL fallback for NAME...")

    response = agentql_page.query_elements(NAME_STEP_QUERY)

    if not response.first_name_input:
        logger.warning("AgentQL could not find first name input")
        return False

    # Extract and cache XPaths for future use
    if DOMPATH_AVAILABLE:
        try:
            if response.first_name_input:
                extract_and_cache_xpath(response.first_name_input, "name_first_name", {"step": "name"})
            if response.last_name_input:
                extract_and_cache_xpath(response.last_name_input, "name_last_name", {"step": "name"})
            if response.next_button:
                extract_and_cache_xpath(response.next_button, "name_next", {"step": "name"})
        except Exception as e:
            logger.warning(f"XPath extraction failed: {e}")

    logger.info(f"Typing name (AgentQL): {identity['firstname']} {identity['lastname']}")

    # Clear and type first name
    response.first_name_input.fill("")
    device.type_text(response.first_name_input, identity["firstname"], "first name (AgentQL)")
    time.sleep(0.2)

    # Clear and type last name
    if response.last_name_input:
        response.last_name_input.fill("")
        device.type_text(response.last_name_input, identity["lastname"], "last name (AgentQL)")

    time.sleep(random.uniform(*DELAYS["after_input"]))

    if response.next_button:
        device.js_click(response.next_button, "next button (AgentQL)")
        time.sleep(random.uniform(*DELAYS["step_transition"]))
        return True

    return False
