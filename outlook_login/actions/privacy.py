"""
Privacy Step Handler for Outlook Login
Handles the "A quick note about your Microsoft account" screen.
"""

import time
import random
from loguru import logger

from amazon.outlook_login.selectors import SELECTORS
from amazon.outlook_login.config import DELAYS
from amazon.outlook.utils.xpath_cache import (
    find_element,
    extract_and_cache_xpath,
    DOMPATH_AVAILABLE,
)

def handle_privacy_step(page, device, agentql_page=None) -> bool:
    logger.info("👤 Handling PRIVACY step")

    try:
        # Priority: OK/Accept button
        ok_btn = find_element(page, "login_privacy_ok_button", timeout=3000, 
                             css_fallback=SELECTORS["privacy"]["ok_button"])
        if ok_btn:
            logger.info("Clicking 'OK' for privacy notice")
            device.js_click(ok_btn, "privacy ok button")
            time.sleep(random.uniform(*DELAYS["step_transition"]))
            return True
            
    except Exception as e:
        logger.debug(f"Selector approach failed for privacy: {e}")

    # AgentQL Fallback
    if agentql_page:
        try:
            logger.info("🧠 Attempting AgentQL fallback for PRIVACY step...")
            response = agentql_page.query_elements("{ privacy_ok_button next_button }")
            
            btn = response.privacy_ok_button or response.next_button
            if btn:
                if response.privacy_ok_button and DOMPATH_AVAILABLE:
                    extract_and_cache_xpath(response.privacy_ok_button, "login_privacy_ok_button", {"step": "privacy"})
                    
                device.tap(btn, "privacy ok button (AgentQL)")
                time.sleep(random.uniform(*DELAYS["step_transition"]))
                return True
        except Exception as e:
            logger.warning(f"AgentQL approach failed for privacy: {e}")

    return False
