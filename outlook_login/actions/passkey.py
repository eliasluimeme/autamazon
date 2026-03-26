"""
Passkey Step Handler for Outlook Login
Handles the "Go passwordless" / Passkey screen.
"""

import time
import random
from loguru import logger

from amazon.outlook_login.selectors import SELECTORS
from amazon.outlook_login.queries import DETECT_STEP_QUERY
from amazon.outlook_login.config import DELAYS
from amazon.outlook.utils.xpath_cache import (
    find_element,
    extract_and_cache_xpath,
    DOMPATH_AVAILABLE,
)

def handle_passkey_step(page, device, agentql_page=None) -> bool:
    logger.info("🔐 Handling PASSKEY step")

    # 1. Try Skip/Cancel via cached or CSS selectors
    try:
        # Priority: Skip for now button
        skip_btn = find_element(page, "login_passkey_skip_button", timeout=2000, 
                               css_fallback=SELECTORS["passkey"]["skip_button"])
        if skip_btn:
            logger.info("Clicking 'Skip for now' for passkey")
            device.js_click(skip_btn, "passkey skip button")
            time.sleep(random.uniform(*DELAYS["step_transition"]))
            return True
            
        # Fallback: Cancel button
        cancel_btn = find_element(page, "login_passkey_cancel_button", timeout=1000,
                                 css_fallback=SELECTORS["passkey"]["cancel_button"])
        if cancel_btn:
            logger.info("Clicking 'Cancel' for passkey")
            device.js_click(cancel_btn, "passkey cancel button")
            time.sleep(random.uniform(*DELAYS["step_transition"]))
            return True
            
    except Exception as e:
        logger.debug(f"Selector approach failed for passkey: {e}")

    # 2. AgentQL Fallback
    if agentql_page:
        try:
            logger.info("🧠 Attempting AgentQL fallback for PASSKEY step...")
            response = agentql_page.query_elements("{ passkey_skip_button cancel_button }")
            
            btn = response.passkey_skip_button or response.cancel_button
            if btn:
                if response.passkey_skip_button and DOMPATH_AVAILABLE:
                    extract_and_cache_xpath(response.passkey_skip_button, "login_passkey_skip_button", {"step": "passkey"})
                
                device.tap(btn, "passkey dismiss button (AgentQL)")
                time.sleep(random.uniform(*DELAYS["step_transition"]))
                return True
        except Exception as e:
            logger.warning(f"AgentQL approach failed for passkey: {e}")

    return False
