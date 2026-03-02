"""
Password Step Handler for Outlook Login
"""

import time
import random
from loguru import logger

from amazon.outlook_login.selectors import SELECTORS
from amazon.outlook_login.queries import PASSWORD_STEP_QUERY
from amazon.outlook_login.config import DELAYS
from amazon.outlook.utils.xpath_cache import (
    find_element,
    extract_and_cache_xpath,
    DOMPATH_AVAILABLE,
)

def handle_password_step(page, identity: dict, device, agentql_page=None) -> bool:
    logger.info("🔑 Handling Login PASSWORD step")

    try:
        if _handle_via_cache(page, identity, device):
            return True
    except Exception as e:
        logger.debug(f"Cached selector approach failed: {e}")

    try:
        if _handle_via_selectors(page, identity, device):
            return True
    except Exception as e:
        logger.debug(f"Selector approach failed: {e}")

    if agentql_page:
        try:
            if _handle_via_agentql(page, agentql_page, identity, device):
                return True
        except Exception as e:
            logger.warning(f"AgentQL approach failed: {e}")

    logger.error("Password string extraction failed across all variants")
    return False

def _handle_via_cache(page, identity, device):
    password_input = find_element(page, "login_password_input", timeout=3000)
    if not password_input:
        return False

    password_input.fill("")
    time.sleep(0.2)
    device.type_text(password_input, identity["password"], "login password input (cached)")
    time.sleep(random.uniform(*DELAYS["after_input"]))

    signin_btn = find_element(page, "login_signin_button", timeout=2000, css_fallback=SELECTORS["password"]["signin_button"])
    if signin_btn:
        device.js_click(signin_btn, "signin button (cached)")
        time.sleep(random.uniform(*DELAYS["step_transition"]))
        return True
    return False

def _handle_via_selectors(page, identity, device):
    password_input = page.locator(SELECTORS["password"]["input"]).first
    if not password_input.is_visible(timeout=3000):
        return False

    password_input.fill("")
    time.sleep(0.2)
    device.type_text(password_input, identity["password"], "login password input")
    time.sleep(random.uniform(*DELAYS["after_input"]))

    signin_btn = page.locator(SELECTORS["password"]["signin_button"]).first
    if signin_btn.is_visible(timeout=2000):
        device.js_click(signin_btn, "signin button")
        time.sleep(random.uniform(*DELAYS["step_transition"]))
        return True
    return False

def _handle_via_agentql(page, agentql_page, identity, device):
    logger.info("🧠 Attempting AgentQL fallback for PASSWORD...")
    response = agentql_page.query_elements(PASSWORD_STEP_QUERY)
    if not response.password_input:
        return False

    if DOMPATH_AVAILABLE:
        try:
            extract_and_cache_xpath(response.password_input, "login_password_input", {"step": "password"})
            if response.signin_button:
                extract_and_cache_xpath(response.signin_button, "login_signin_button", {"step": "password"})
        except Exception: pass

    response.password_input.fill("")
    time.sleep(0.2)
    device.type_text(response.password_input, identity["password"], "login password input (AgentQL)")
    time.sleep(random.uniform(*DELAYS["after_input"]))

    if response.signin_button:
        device.tap(response.signin_button, "signin button (AgentQL)")
        time.sleep(random.uniform(*DELAYS["step_transition"]))
        return True
    return False
