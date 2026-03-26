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

    # 1. Try Cancel/Skip via cached or CSS selectors
    try:
        # Priority 1: Cancel button (Requested by user as preferred)
        cancel_btn = find_element(page, "login_passkey_cancel_button", timeout=1000,
                                 css_fallback=SELECTORS["passkey"]["cancel_button"])
        if cancel_btn:
            logger.info("Found 'Cancel' button, clicking it...")
            device.js_click(cancel_btn, "passkey cancel button")
            time.sleep(random.uniform(*DELAYS["step_transition"]))
            return True

        # Priority 2: Skip for now button
        skip_btn = find_element(page, "login_passkey_skip_button", timeout=1000, 
                               css_fallback=SELECTORS["passkey"]["skip_button"])
        if skip_btn:
            logger.info("Found 'Skip for now' button, clicking it...")
            device.js_click(skip_btn, "passkey skip button")
            time.sleep(random.uniform(*DELAYS["step_transition"]))
            return True
            
    except Exception as e:
        logger.debug(f"Selector approach failed for passkey: {e}")

    # 2. AgentQL Fallback
    if agentql_page:
        try:
            logger.info("🧠 Attempting AgentQL fallback for PASSKEY step...")
            # We explicitly ask for both to avoid AgentQL misidentifying one as the other
            response = agentql_page.query_elements("{ cancel_button skip_for_now_button try_again_button }")
            
            # Prioritize Cancel as requested
            btn = response.cancel_button or response.skip_for_now_button
            
            if btn:
                if response.cancel_button and DOMPATH_AVAILABLE:
                    extract_and_cache_xpath(response.cancel_button, "login_passkey_cancel_button", {"step": "passkey"})
                elif response.skip_for_now_button and DOMPATH_AVAILABLE:
                    extract_and_cache_xpath(response.skip_for_now_button, "login_passkey_skip_button", {"step": "passkey"})
                
                logger.info(f"Clicking {'Cancel' if response.cancel_button else 'Skip'} button (AgentQL)")
                device.tap(btn, "passkey dismiss button (AgentQL)")
                time.sleep(random.uniform(*DELAYS["step_transition"]))
                return True
            elif response.try_again_button:
                logger.warning("AgentQL found 'Try again' but no 'Cancel' or 'Skip'. This might be an error page.")
        except Exception as e:
            logger.warning(f"AgentQL approach failed for passkey: {e}")

    return False
