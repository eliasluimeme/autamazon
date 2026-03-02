"""
Skip Step Handler for Outlook Login
Handles the "Skip for now" screen.
"""

import time
import random
from loguru import logger

from amazon.outlook_login.selectors import SELECTORS
from amazon.outlook_login.queries import SKIP_STEP_QUERY
from amazon.outlook_login.config import DELAYS
from amazon.outlook.utils.xpath_cache import (
    find_element,
    extract_and_cache_xpath,
    DOMPATH_AVAILABLE,
)

def handle_skip_step(page, device, agentql_page=None) -> bool:
    logger.info("⏭ Handling SKIP step")

    try:
        skip_btn = find_element(page, "login_skip_button", timeout=3000, css_fallback=SELECTORS["skip"]["skip_button"])
        if skip_btn:
            device.js_click(skip_btn, "skip button")
            time.sleep(random.uniform(*DELAYS["step_transition"]))
            return True
    except Exception as e:
        logger.debug(f"Selector approach failed: {e}")

    if agentql_page:
        try:
            logger.info("🧠 Attempting AgentQL fallback for SKIP step...")
            response = agentql_page.query_elements(SKIP_STEP_QUERY)
            if response.skip_for_now_button:
                if DOMPATH_AVAILABLE:
                    extract_and_cache_xpath(response.skip_for_now_button, "login_skip_button", {"step": "skip"})
                device.tap(response.skip_for_now_button, "skip button (AgentQL)")
                time.sleep(random.uniform(*DELAYS["step_transition"]))
                return True
        except Exception as e:
            logger.warning(f"AgentQL approach failed: {e}")

    return False
