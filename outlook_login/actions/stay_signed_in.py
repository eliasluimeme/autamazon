"""
Stay Signed In Step Handler for Outlook Login
Handles the 'Stay signed in' prompt for login
"""

import time
import random
from loguru import logger

from amazon.outlook_login.selectors import SELECTORS
from amazon.outlook_login.queries import STAY_SIGNED_IN_STEP_QUERY
from amazon.outlook_login.config import DELAYS
from amazon.outlook.utils.xpath_cache import (
    find_element,
    extract_and_cache_xpath,
    DOMPATH_AVAILABLE,
)

def handle_stay_signed_in_step(page, device, agentql_page=None) -> bool:
    logger.info("ℹ️ Handling STAY_SIGNED_IN step")

    try:
        checkbox_label = find_element(page, "login_stay_signed_in_checkbox_label", timeout=2000, css_fallback=SELECTORS["stay_signed_in"]["checkbox_label"])
        # In Playwright, xpath string needs locator(f"xpath={selector}") inside find_element, or similar.
        # But wait, find_element falls back to css_fallback which takes multiple comma separated, xpath is not standard css.
        # So we can just fallback to raw locator.
        if not checkbox_label:
            checkbox_label = page.locator(f"xpath={SELECTORS['stay_signed_in']['checkbox_label']}").first

        if checkbox_label and checkbox_label.is_visible(timeout=1000):
            try:
                device.tap(checkbox_label, "stay signed in checkbox")
                time.sleep(random.uniform(*DELAYS["after_click"]))
            except: pass

        yes_btn = find_element(page, "login_stay_signed_in_yes", timeout=2000, css_fallback=SELECTORS["stay_signed_in"]["yes_button"])
        if yes_btn:
            device.js_click(yes_btn, "stay signed in yes button")
            time.sleep(random.uniform(*DELAYS["step_transition"]))
            return True
    except Exception as e:
        logger.debug(f"Selector approach failed for stay signed in: {e}")

    if agentql_page:
        try:
            logger.info("🧠 Attempting AgentQL fallback for STAY_SIGNED_IN...")
            response = agentql_page.query_elements(STAY_SIGNED_IN_STEP_QUERY)
            if response.stay_signed_in_checkbox:
                device.tap(response.stay_signed_in_checkbox, "stay signed in checkbox")
                time.sleep(random.uniform(*DELAYS["after_click"]))
            
            if response.stay_signed_in_yes_button:
                if DOMPATH_AVAILABLE:
                    extract_and_cache_xpath(response.stay_signed_in_yes_button, "login_stay_signed_in_yes", {"step": "stay_signed_in"})
                device.tap(response.stay_signed_in_yes_button, "stay signed in yes (AgentQL)")
                time.sleep(random.uniform(*DELAYS["step_transition"]))
                return True
        except Exception as e:
            logger.warning(f"AgentQL approach failed: {e}")

    return False
