"""
Step Detection for Outlook Signup

Detects which step of the signup flow we are currently on.
Uses selector-first approach with AgentQL fallback.
"""

import time
from loguru import logger

from amazon.outlook.selectors import SELECTORS
from amazon.outlook.queries import DETECT_STEP_QUERY
from amazon.outlook.utils.xpath_cache import (
    find_element,
    get_cached_xpath,
    extract_and_cache_xpath,
    DOMPATH_AVAILABLE,
)


def detect_current_step(page, agentql_page=None) -> str:
    """
    Detect the current signup step by checking for key elements.
    
    Priority:
    0. Try cached selectors (fastest — uses cached XPath + CSS)
    1. Try CSS selectors (fast)
    2. Fallback to AgentQL (slow but robust)
    
    Args:
        page: Playwright page object
        agentql_page: Optional AgentQL-wrapped page
        
    Returns:
        Step name: EMAIL, PASSWORD, NAME, DOB, CAPTCHA, PRIVACY, SUCCESS, or UNKNOWN
    """
    
    # Priority 0: Try cached selectors (Fastest, zero cost — XPath then CSS)
    step = _detect_via_cache(page)
    if step != "UNKNOWN":
        logger.debug(f"Step detected via cache: {step}")
        return step
    
    # Priority 1: AgentQL (Slow but 100% Reliable - Reverted to primary source of truth)
    if agentql_page:
        step = _detect_via_agentql(page, agentql_page)
        if step != "UNKNOWN":
            logger.debug(f"Step detected via AgentQL: {step}")
            return step
    
    # Priority 2: CSS Selector detection (Fast fallback, but prone to false positives)
    # Using this as a fallback for when AgentQL is unavailable or fails
    step = _detect_via_selectors(page)
    if step != "UNKNOWN":
        logger.debug(f"Step detected via selectors: {step}")
        return step
    
    return "UNKNOWN"


def _detect_via_cache(page) -> str:
    """Detect step using cached XPaths + CSS from data/xpath_cache/outlook_selectors.json."""
    
    # Mapping of step names to their characteristic cache keys
    indicator_keys = {
        "EMAIL": "email_input",
        "PASSWORD": "password_input",
        "NAME": "name_first_name",
        "DOB": "dob_year",
        "CAPTCHA": "captcha_button",
        "PRIVACY": "privacy_ok_button",
        "STAY_SIGNED_IN": "stay_signed_in_yes",
        "PASSKEY": "passkey_skip_button",
    }
    
    # Check each step indicator using find_element (tries XPath then CSS)
    for step, key in indicator_keys.items():
        el = find_element(page, key, timeout=500)
        if el:
            return step
                
    return "UNKNOWN"



def _detect_via_selectors(page) -> str:
    """Detect step using CSS selectors."""
    
    # Check in reverse order of flow (most specific first)
    # NOTE: SUCCESS check is done AFTER PASSKEY/PRIVACY checks to avoid
    # premature detection when on interruption/passkey pages
    
    # Passkey / Interruption check
    try:
        # Check URL first for interruption (fast check)
        url = page.url.lower()
        if "interruption" in url or "passkey" in url:
            logger.info(f"Detected PASSKEY step via URL: {url}")
            return "PASSKEY"
        
        if "error.aspx?errcode=" in url:
            logger.error(f"Detected Outlook error page via URL: {url}")
            return "ERROR"
        
        # PRIMARY CHECK: Search page content for passkey-related text
        # This works even when native dialogs are overlaying the page
        try:
            page_content = page.content().lower()
            passkey_text_patterns = [
                "setting up your passkey",
                "go passwordless",
                "create a passkey",
                "use a passkey",
                "couldn't create a passkey",
                "we couldn't create a passkey",
            ]
            for pattern in passkey_text_patterns:
                if pattern in page_content:
                    logger.info(f"Detected PASSKEY step via page content: '{pattern}'")
                    return "PASSKEY"
        except Exception as e:
            logger.debug(f"Page content check failed: {e}")
        
        # SECONDARY CHECK: Use get_by_text for visible text
        try:
            if page.get_by_text("Setting up your passkey").first.is_visible(timeout=500):
                logger.info("Detected PASSKEY step via get_by_text")
                return "PASSKEY"
        except:
            pass
        
        # Check for specific passkey/interruption headers or buttons
        passkey_indicators = [
            # Skip for now button (common for passkey prompt)
            "button:has-text('Skip for now')",
            "a:has-text('Skip for now')",
            
            # Passkey headers and text - using more flexible matching
            "text=Setting up your passkey",
            "text=Go passwordless",
            
            # Error state (seen in previous descriptions)
            "text=We couldn't create a passkey",
        ]
        
        for indicator in passkey_indicators:
            try:
                if page.locator(indicator).first.is_visible(timeout=300):
                    logger.info(f"Detected PASSKEY step via indicator: {indicator}")
                    return "PASSKEY"
            except:
                pass
        
        # Check for Cancel button when no other obvious form elements are visible
        # This helps catch the passkey interruption page
        try:
            cancel_btn = page.locator("button:has-text('Cancel')").first
            if cancel_btn.is_visible(timeout=300):
                # Make sure we're not on a form page (no email/password inputs)
                has_form_inputs = False
                try:
                    has_form_inputs = (
                        page.locator(SELECTORS["email"]["input"]).first.is_visible(timeout=200) or
                        page.locator(SELECTORS["password"]["input"]).first.is_visible(timeout=200) or
                        page.locator(SELECTORS["name"]["first_name"]).first.is_visible(timeout=200)
                    )
                except:
                    pass
                
                if not has_form_inputs:
                    logger.info("Detected PASSKEY step via Cancel button (no form visible)")
                    return "PASSKEY"
        except:
            pass
            
    except:
        pass
    
    # Stay Signed In check (comes after passkey)
    try:
        # Check page content first
        try:
            page_content = page.content().lower()
            if "stay signed in" in page_content:
                logger.info("Detected STAY_SIGNED_IN step via page content")
                return "STAY_SIGNED_IN"
        except:
            pass
        
        # Check for Yes/No buttons with Stay signed in header
        try:
            if page.get_by_text("Stay signed in").first.is_visible(timeout=300):
                logger.info("Detected STAY_SIGNED_IN step via get_by_text")
                return "STAY_SIGNED_IN"
        except:
            pass
        
        # Check for the specific Yes button on this page
        stay_signed_indicators = [
            "text=Stay signed in",
            "h1:has-text('Stay signed in')",
        ]
        for indicator in stay_signed_indicators:
            try:
                if page.locator(indicator).first.is_visible(timeout=300):
                    return "STAY_SIGNED_IN"
            except:
                pass
    except:
        pass
    
    # ---------------------------------------------------------
    # CORE FLOW STEPS (Moved up for priority)
    # ---------------------------------------------------------

    # Email check
    try:
        if page.locator(SELECTORS["email"]["input"]).first.is_visible(timeout=500):
            return "EMAIL"
    except:
        pass

    # Password check
    try:
        if page.locator(SELECTORS["password"]["input"]).first.is_visible(timeout=500):
            # Make sure it's not alongside email (some flows show both)
            email_visible = False
            try:
                email_visible = page.locator(SELECTORS["email"]["input"]).first.is_visible(timeout=300)
            except:
                pass
            if not email_visible:
                return "PASSWORD"
    except:
        pass

    # Name check
    try:
        if page.locator(SELECTORS["name"]["first_name"]).first.is_visible(timeout=500):
            return "NAME"
    except:
        pass

    # DOB check (year input is distinctive)
    try:
        if page.locator(SELECTORS["dob"]["year_input"]).first.is_visible(timeout=500):
            return "DOB"
    except:
        pass

    # ---------------------------------------------------------
    # INTERRUPTIONS / END STATES
    # ---------------------------------------------------------
    
    # SUCCESS check - placed AFTER passkey/stay-signed-in checks to avoid premature detection
    try:
        url = page.url.lower()
        # After successful signup, user lands on account.microsoft.com or outlook.live.com
        # Exclude pages that are part of the signup flow
        exclusions = [
            "privacynotice",
            "privacy",
            "interruption",
            "passkey",
            "signup",
            "proofs",
            "identity",
        ]
        
        is_success_url = (
            ("account.microsoft.com" in url or "outlook.live.com/mail" in url)
            and not any(excl in url for excl in exclusions)
        )
        
        if is_success_url:
            # Double-check we're not on a setup/interruption page by checking page content
            try:
                page_content = page.content().lower()
                setup_indicators = [
                    "setting up your passkey",
                    "stay signed in",
                    "go passwordless",
                    "create a passkey",
                ]
                if not any(ind in page_content for ind in setup_indicators):
                    logger.info(f"Detected SUCCESS via URL: {url}")
                    return "SUCCESS"
            except:
                # If we can't check content, trust the URL
                logger.info(f"Detected SUCCESS via URL: {url}")
                return "SUCCESS"
    except:
        pass
    
    # Success check - element-based fallback
    try:
        if page.locator(SELECTORS["success"]["inbox"]).first.is_visible(timeout=500):
            return "SUCCESS"
    except:
        pass
    
    # Privacy notice check (comes after CAPTCHA)
    try:
        url = page.url.lower()
        if "privacynotice" in url or "privacy" in url:
            # Also check for OK button
            ok_selectors = ["button:has-text('OK')", "button#acceptButton", "#idBtn_Accept"]
            for sel in ok_selectors:
                try:
                    if page.locator(sel).first.is_visible(timeout=300):
                        return "PRIVACY"
                except:
                    pass
    except:
        pass
    
    # CAPTCHA check
    try:
        # Check for "Let's prove you're human" text or press and hold
        # Refined to avoid overly broad matches like just "hold"
        captcha_indicators = [
            ":text('prove you')",
            ":text('Press and hold')",
            "button:has-text('Press and hold')",
            "button:has-text('Hold to confirm')",
        ]
        for indicator in captcha_indicators:
            try:
                if page.locator(indicator).first.is_visible(timeout=300):
                    return "CAPTCHA"
            except:
                pass
        
        # Frame-based check
        if page.locator(SELECTORS["captcha"]["frame"]).first.is_visible(timeout=500):
            return "CAPTCHA"
    except:
        pass
    


def _detect_via_agentql(page, agentql_page) -> str:
    """Detect step using AgentQL query with XPath extraction for future caching."""
    try:
        # Use a fresh query for detection to ensure accuracy
        response = agentql_page.query_elements(DETECT_STEP_QUERY)
        
        # 1. Check for core signup steps first (Priority)
        if response.email_input:
            if DOMPATH_AVAILABLE:
                extract_and_cache_xpath(response.email_input, "email_input", {"step": "detect"})
            return "EMAIL"
            
        if response.password_input:
            if DOMPATH_AVAILABLE:
                extract_and_cache_xpath(response.password_input, "password_input", {"step": "detect"})
            return "PASSWORD"
            
        if response.first_name_input:
            if DOMPATH_AVAILABLE:
                extract_and_cache_xpath(response.first_name_input, "name_first_name", {"step": "detect"})
            return "NAME"
            
        if response.birth_date_fields and response.birth_date_fields.year_input:
            if DOMPATH_AVAILABLE:
                extract_and_cache_xpath(response.birth_date_fields.year_input, "dob_year", {"step": "detect"})
            return "DOB"
        
        # 2. Check for PRIVACY FIRST (before success) - URL-based check
        # This prevents false SUCCESS detection when on privacynotice.account.microsoft.com
        try:
            url = page.url.lower()
            if "privacynotice" in url or "privacy" in url:
                return "PRIVACY"
        except:
            pass
            
        # 3. Check for success
        if response.inbox_link or response.welcome_message:
            return "SUCCESS"
        
        # 4. Check for captcha (Stricter validation)
        if response.captcha_frame or response.press_and_hold_button:
            # Extra validation: if it's the email page and we somehow see a 'captcha' frame 
            # (which might be a telemetry/advertising iframe), check if email input is REALLY gone.
            if response.email_input:
                return "EMAIL"
                
            if DOMPATH_AVAILABLE:
                try:
                    if response.captcha_frame:
                        extract_and_cache_xpath(response.captcha_frame, "captcha_frame", {"step": "detect"})
                    if response.press_and_hold_button:
                        extract_and_cache_xpath(response.press_and_hold_button, "captcha_button", {"step": "detect"})
                except:
                    pass
            return "CAPTCHA"

    except Exception as e:
        logger.warning(f"AgentQL step detection failed: {e}")
    
    return "UNKNOWN"

