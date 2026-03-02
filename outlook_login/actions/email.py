"""
Email Step Handler for Outlook Login

Handles enterng the email address for login.
"""

import time
import random
from loguru import logger

from amazon.outlook_login.selectors import SELECTORS
from amazon.outlook_login.queries import EMAIL_STEP_QUERY
from amazon.outlook_login.config import DELAYS
from amazon.outlook.utils.xpath_cache import (
    find_element,
    extract_and_cache_xpath,
    DOMPATH_AVAILABLE,
)

def handle_email_step(page, identity: dict, device, agentql_page=None, retry_count: int = 0) -> bool:
    logger.info(f"📧 Handling Login EMAIL step (retry: {retry_count})")

    # Priority 0: Try cached selectors
    try:
        if _handle_via_cache(page, identity, device):
            return True
    except Exception as e:
        logger.debug(f"Cached selector approach failed: {e}")

    # Priority 1: Try CSS selectors
    try:
        if _handle_via_selectors(page, identity, device):
            return True
    except Exception as e:
        logger.debug(f"Selector approach failed: {e}")

    # Priority 2: AgentQL fallback
    if agentql_page:
        try:
            if _handle_via_agentql(page, agentql_page, identity, device):
                return True
        except Exception as e:
            logger.warning(f"AgentQL approach failed: {e}")

    logger.error("Email step failed with all approaches")
    return False


def _handle_via_cache(page, identity: dict, device) -> bool:
    email_input = find_element(page, "login_email_input", timeout=3000)
    if not email_input:
        return False

    logger.info("🔄 Attempting EMAIL via cached selectors...")
    email_to_type = identity["email"] if "email" in identity else f"{identity['email_handle']}@outlook.com"

    email_input.fill("")
    time.sleep(0.2)
    device.type_text(email_input, email_to_type, "login email input (cached)")

    time.sleep(random.uniform(*DELAYS["after_input"]))

    next_btn = find_element(page, "login_email_next", timeout=2000, css_fallback=SELECTORS["email"]["next_button"])
    if next_btn:
        device.js_click(next_btn, "next button (cached)")
        time.sleep(random.uniform(*DELAYS["step_transition"]))
        return True

    return False


def _handle_via_selectors(page, identity: dict, device) -> bool:
    email_input = page.locator(SELECTORS["email"]["input"]).first
    if not email_input.is_visible(timeout=3000):
        return False

    email_to_type = identity["email"] if "email" in identity else f"{identity['email_handle']}@outlook.com"
    email_input.fill("")
    time.sleep(0.2)
    device.type_text(email_input, email_to_type, "login email input")

    time.sleep(random.uniform(*DELAYS["after_input"]))

    next_btn = page.locator(SELECTORS["email"]["next_button"]).first
    if next_btn.is_visible(timeout=2000):
        device.js_click(next_btn, "next button")
        time.sleep(random.uniform(*DELAYS["step_transition"]))
        return True

    return False


def _handle_via_agentql(page, agentql_page, identity: dict, device) -> bool:
    logger.info("🧠 Attempting AgentQL fallback for EMAIL...")

    response = agentql_page.query_elements(EMAIL_STEP_QUERY)
    if not response.email_input:
        return False

    if DOMPATH_AVAILABLE:
        try:
            if response.email_input:
                extract_and_cache_xpath(response.email_input, "login_email_input", {"step": "email"})
            if response.next_button:
                extract_and_cache_xpath(response.next_button, "login_email_next", {"step": "email"})
        except Exception: pass

    email_to_type = identity["email"] if "email" in identity else f"{identity['email_handle']}@outlook.com"

    response.email_input.fill("")
    time.sleep(0.2)
    device.type_text(response.email_input, email_to_type, "login email input (AgentQL)")

    time.sleep(random.uniform(*DELAYS["after_input"]))

    if response.next_button:
        device.tap(response.next_button, "next button (AgentQL)")
        time.sleep(random.uniform(*DELAYS["step_transition"]))
        return True

    return False
