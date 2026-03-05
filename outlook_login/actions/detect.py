"""
Step Detection for Outlook Login

Detects which step of the login flow we are currently on.
Uses selector-first approach with AgentQL fallback.
"""

import time
from loguru import logger

from amazon.outlook_login.selectors import SELECTORS
from amazon.outlook_login.queries import DETECT_STEP_QUERY
from amazon.outlook.utils.xpath_cache import (
    find_element,
    extract_and_cache_xpath,
    DOMPATH_AVAILABLE,
)

def detect_current_step(page, agentql_page=None) -> str:
    if page.is_closed():
        logger.error("Page closed. Cannot detect Outlook login step.")
        return "UNKNOWN"
        
    if _is_network_error(page):
        logger.error("🛑 Browser network error detected.")
        return "ERROR"
        
    # Priority 0.5: Try cached selectors
    step = _detect_via_cache(page)
    if step != "UNKNOWN":
        logger.debug(f"Step detected via cache: {step}")
        return step
    
    # Priority 1: AgentQL
    if agentql_page:
        step = _detect_via_agentql(page, agentql_page)
        if step != "UNKNOWN":
            logger.debug(f"Step detected via AgentQL: {step}")
            return step
    
    # Priority 2: CSS Selectors fallback
    step = _detect_via_selectors(page)
    if step != "UNKNOWN":
        logger.debug(f"Step detected via selectors: {step}")
        return step
    
    return "UNKNOWN"


def _is_network_error(page) -> bool:
    """Detect if we are on a browser error page OR a Microsoft error page."""
    try:
        title = page.title().lower()
        if "site can't be reached" in title or "error" in title:
            return True
        
        # --- Microsoft "Something went wrong" error page detection ---
        # IMPORTANT: Must NOT false-positive on passkey/interruption pages which
        # also contain "something went wrong" text.
        try:
            url = page.url.lower()
            is_microsoft_domain = any(d in url for d in (
                "signup.live.com", "login.live.com", "account.live.com",
                "login.microsoftonline.com", "account.microsoft.com",
            ))
            if is_microsoft_domain:
                # Skip if URL indicates a known flow page
                known_flow_urls = (
                    "passkey", "interrupt", "fido", "privacynotice",
                    "proofs", "identity", "signup",
                )
                if any(kw in url for kw in known_flow_urls):
                    pass  # Not an error page — it's a known flow step
                else:
                    page_text = page.content().lower()
                    
                    # Skip if page contains passkey/interruption-specific content
                    passkey_exclusions = [
                        "create a passkey", "passkey", "go passwordless",
                        "setting up your", "stay signed in",
                    ]
                    is_passkey_page = any(p in page_text for p in passkey_exclusions)
                    
                    if not is_passkey_page:
                        ms_error_patterns = [
                            "something went wrong",
                            "we can't complete this action",
                            "this service is not available",
                            "service unavailable",
                            "temporarily unavailable",
                            "we're having trouble",
                            "an error occurred",
                            "our services aren't available right now",
                        ]
                        has_error_text = any(p in page_text for p in ms_error_patterns)
                        if has_error_text:
                            has_form = any(tag in page_text for tag in (
                                'id="membername"', 'id="passwordinput"',
                                'id="firstname"', 'id="birthyear"',
                                'name="membername"', 'name="passwd"',
                                'type="email"', 'type="password"',
                            ))
                            if not has_form:
                                logger.warning(
                                    f"🛑 Microsoft error page detected: "
                                    f"{[p for p in ms_error_patterns if p in page_text]}"
                                )
                                return True
        except Exception:
            pass
        
        # --- URL-based error detection ---
        try:
            url = page.url.lower()
            if "error.aspx" in url or "errcode=" in url:
                logger.warning(f"🛑 Microsoft error URL detected: {url}")
                return True
        except Exception:
            pass
            
        error_indicators = [
            "#main-frame-error",
            "text=ERR_TUNNEL_CONNECTION_FAILED",
            "text=ERR_CONNECTION_REFUSED",
            "text=ERR_CONNECTION_TIMED_OUT",
            "text=ERR_PROXY_CONNECTION_FAILED",
            "text=ERR_SSL_PROTOCOL_ERROR",
        ]
        for sel in error_indicators:
            try:
                if page.locator(sel).first.is_visible(timeout=200):
                    return True
            except: pass
            
        content = page.content()
        if len(content) < 300 and "<html><head></head><body>" in content.lower():
            return True
    except Exception:
        pass
    return False


def _detect_via_cache(page) -> str:
    # We use custom cache keys specific to login to avoid clash with signup
    indicator_keys = {
        "EMAIL": "login_email_input",
        "PASSWORD": "login_password_input",
        "SKIP": "login_skip_button",
        "STAY_SIGNED_IN": "login_stay_signed_in_yes",
    }
    
    for step, key in indicator_keys.items():
        el = find_element(page, key, timeout=500)
        if el:
            return step
                
    return "UNKNOWN"


def _detect_via_selectors(page) -> str:
    # Success check
    try:
        url = page.url.lower()
        exclusions = ["interruption", "passkey", "login"]
        if "account.microsoft.com" in url or "outlook.live.com/mail" in url:
            if not any(excl in url for excl in exclusions):
                return "SUCCESS"
    except: pass
    
    try:
        if page.locator(SELECTORS["success"]["inbox"]).first.is_visible(timeout=500):
            return "SUCCESS"
    except: pass

    # Skip for now
    try:
        if page.locator(SELECTORS["skip"]["skip_button"]).first.is_visible(timeout=500):
            return "SKIP"
    except: pass

    # Stay Signed In
    try:
        if page.locator(SELECTORS["stay_signed_in"]["yes_button"]).first.is_visible(timeout=500):
            return "STAY_SIGNED_IN"
    except: pass

    # Password
    try:
        if page.locator(SELECTORS["password"]["input"]).first.is_visible(timeout=500):
            return "PASSWORD"
    except: pass

    # Email
    try:
        if page.locator(SELECTORS["email"]["input"]).first.is_visible(timeout=500):
            return "EMAIL"
    except: pass

    return "UNKNOWN"


def _detect_via_agentql(page, agentql_page) -> str:
    try:
        # Avoid agentql false SUCCESS detection
        try:
            url = page.url.lower()
            if "account.microsoft.com" in url or "outlook.live.com/mail" in url:
                exclusions = ["interruption", "passkey", "login"]
                if not any(excl in url for excl in exclusions):
                    return "SUCCESS"
        except: pass

        response = agentql_page.query_elements(DETECT_STEP_QUERY)
        
        if response.email_input:
            if DOMPATH_AVAILABLE:
                extract_and_cache_xpath(response.email_input, "login_email_input", {"step": "detect"})
            return "EMAIL"
            
        if response.password_input:
            if DOMPATH_AVAILABLE:
                extract_and_cache_xpath(response.password_input, "login_password_input", {"step": "detect"})
            return "PASSWORD"
            
        if response.skip_for_now_button:
            if DOMPATH_AVAILABLE:
                extract_and_cache_xpath(response.skip_for_now_button, "login_skip_button", {"step": "detect"})
            return "SKIP"
            
        if response.stay_signed_in_yes_button:
            if DOMPATH_AVAILABLE:
                extract_and_cache_xpath(response.stay_signed_in_yes_button, "login_stay_signed_in_yes", {"step": "detect"})
            return "STAY_SIGNED_IN"

    except Exception as e:
        logger.warning(f"AgentQL login detection failed: {e}")
    
    return "UNKNOWN"
