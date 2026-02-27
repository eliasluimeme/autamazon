"""
Amazon Signup State Detection

Robustly detects the current step in the Amazon signup flow using a prioritized
check mechanism (Interstitials > Verification > Success > Core Flow).

Mirrors the pattern used in the Outlook module.
"""

from loguru import logger
import time
from amazon.agentql_helper import query_amazon, try_cached_selectors

# --- SELECTOR DEFINITIONS ---
AMAZON_SELECTORS = {
    "interstitials": {
        "captcha": [
            "text='Enter the characters'",
            "text='Type the characters'",
            "img[src*='captcha']",
            "#captchacharacters",
            "input[name='cvf_captcha_input']",
            "text='Solve this puzzle'",  # Sometimes captcha is called puzzle too
        ],
        "puzzle": [
            # Use partial matching - :has-text() or text= without quotes
            ":has-text('Solve this puzzle')",
            "h1:has-text('Solve this puzzle')",
            ":has-text('Choose all')",
            ":has-text('Solved:')",
            "button:has-text('Confirm')",
            "iframe[src*='arkoselabs']",
            "iframe[src*='funcaptcha']",
            "#funcaptcha",
            "#arkose",
        ],
        "passkey": [
            "text='Use face ID, fingerprint, or PIN'",
            "text='Set up a passkey'",
            "#passkey-nudge-skip-button",
            "button:has-text('Not now')",
            "button:has-text('Skip')",
        ],
    },
    "payment": [
        "text='How would you like to pay?'",
        "text='Add a credit or debit card'",
        "button:has-text('Place your order')",
        "input[value='Place your order']",
        "#placeYourOrder",
        "h1:has-text('Order summary')",
        "text='Order total'",
    ],
    "verification": {
        "otp": [
            "text='Enter the code'",
            "text='Enter security code'",
            "text='Verify email address'",
            "input[name='code']",
            "#cvf-input-code",
            "input[placeholder='Code']",
        ],
        "add_mobile": [
            # Use partial matching for better detection
            ":has-text('Add mobile number')",
            "h1:has-text('Add mobile number')",
            ":has-text('Step 1 of 2')",
            ":has-text('New mobile number')",
            "input[name='cvf_phone_num']",
            # "input[type='tel']", # Too broad! Matches payment forms
            "button:has-text('Add mobile number')",
        ],
    },
    "success": {
        "indicators": [
            "#nav-link-accountList-nav-line-1:text('Hello,')",
            "text='Hello, [Name]'", # Dynamic check needed
            "a#nav-item-signout",
            "text='Sign Out'",
            "div.a-box-group", # Common account dashboard
        ],
        "urls": [
            "/gp/yourstore",
            "/homepage",
            "ref=nav_ya_signin",
            # "/dppui/pay-select", # Moved to payment detection
            "/gp/aw/d/",
        ]
    },
    "core": {
        "registration_form": [
            "input[name='customerName']",
            "#ap_customer_name",
            "text='Create account'", # Careful, this text is on signin page too
            "h1:has-text('Create account')",
        ],
        "signin_choice": [
            "input[name='create'][type='radio']",
            "label:has-text('Create account')",
            "#createAccountSubmit",
            "button:has-text('Create account')",
            "text='New to Amazon?'",
        ],
        "email_entry": [
            "input[name='email']",
            "h1:has-text('Sign in')",
        ],
        "new_customer_intent": [
            "text=Looks like you're new to Amazon",
            "button:has-text('Proceed to create an account')",
        ]
    }
}


def detect_signup_state(page, agentql_page=None) -> str:
    """
    Detect the current state of the Amazon signup flow.
    
    Returns one of:
        - 'captcha'
        - 'puzzle'
        - 'verification' (OTP)
        - 'passkey_nudge'
        - 'success'
        - 'registration_form'
        - 'signin_choice'
        - 'email_signin_entry'
        - 'new_customer_intent'
        - 'add_mobile'
        - 'unknown'
    """
    if page.is_closed():
        logger.error("Page is closed. Cannot detect state.")
        return "unknown"
        
    # ============================================================
    # 🔑 Priority 0: Network/Browser Error Check (Fast & Essential)
    # ============================================================
    if _is_network_error(page):
        logger.error("🛑 Browser network error detected (Amazon unreachable).")
        return "error"
        
    url = page.url.lower()
    
    # ============================================================
    # 🔑 Priority 0.5: Try Cached Detectors (Fastest)
    # ============================================================
    state = _detect_via_cache(page)
    if state:
        logger.debug(f"Detected State via Cache: {state}")
        return state

    # ============================================================
    # 🔑 Priority 1: Check for NEW CUSTOMER INTENT first
    # This page has 'arb=' in URL but is NOT a puzzle!
    # ============================================================
    if "/ax/claim/intent" in url:
        logger.info("Detected NEW_CUSTOMER_INTENT via URL '/ax/claim/intent'")
        return "new_customer_intent"
        
    # Also check by content (fallback)
    try:
        if page.locator("text='Looks like you're new to Amazon'").first.is_visible(timeout=300):
            logger.info("Detected NEW_CUSTOMER_INTENT via page content")
            return "new_customer_intent"
        if page.locator("button:has-text('Proceed to create an account')").first.is_visible(timeout=300):
            logger.info("Detected NEW_CUSTOMER_INTENT via 'Proceed' button")
            return "new_customer_intent"
    except:
        pass
    
    # ============================================================
    # Priority 2: Check Interstitials (Blockers)
    # ============================================================
    
    # Puzzle check (URL param AFTER intent check)
    # Only return puzzle if we see puzzle-specific content too
    if "arb=" in url:
        # Double-check it's actually a puzzle, not just arb param
        try:
            if page.locator("text='Solve this puzzle'").first.is_visible(timeout=500):
                logger.debug("Detected PUZZLE via 'arb=' + puzzle text")
                return "puzzle"
            # Check for funcaptcha iframe
            if page.locator("iframe[src*='arkoselabs'], iframe[src*='funcaptcha']").first.is_visible(timeout=300):
                logger.debug("Detected PUZZLE via 'arb=' + iframe")
                return "puzzle"
        except:
            pass
        # If arb= but no puzzle content, might be verification or other step
        # Fall through to other checks
        
    state = _detect_interstitials(page)
    if state:
        logger.info(f"Detected Interstitial State: {state}")
        return state
        
    # ============================================================
    # Priority 3: Check Payment/Success (BEFORE Verification)
    # This prevents 'add_mobile' false positives on input[type='tel']
    # ============================================================
    if _detect_payment(page):
        logger.info("Detected Payment Page (Success)")
        return "success"

    state = _detect_success(page)
    if state:
        logger.info(f"Detected Success State: {state}")
        return state

    # ============================================================
    # Priority 4: Check Verification (OTP / Mobile)
    # ============================================================
    state = _detect_verification(page)
    if state:
        logger.info(f"Detected Verification State: {state}")
        return state
        
    # ============================================================
    # Priority 5: Check Core Flow (Forms)
    # ============================================================
    state = _detect_core_flow(page)
    if state:
        logger.info(f"Detected Core Flow State: {state}")
        return state
        
    # 5. AgentQL Fallback
    if agentql_page:
        state = _detect_via_agentql(page, agentql_page)
        if state:
            logger.info(f"Detected State via AgentQL: {state}")
            return state
            
    # Default to unknown
    logger.debug(f"State unknown for URL: {url}")
    return "unknown"


def _detect_payment(page) -> bool:
    """Check for Payment Selection / Place Order page."""
    url = page.url.lower()
    
    if "/dppui/pay-select" in url:
        return True
        
    for sel in AMAZON_SELECTORS["payment"]:
        try:
            if page.locator(sel).first.is_visible(timeout=200):
                return True
        except:
            pass
    return False



def _detect_interstitials(page) -> str | None:
    """Check for CAPTCHA, Puzzle, Passkey."""
    
    # Check Puzzle
    for sel in AMAZON_SELECTORS["interstitials"]["puzzle"]:
        try:
            if page.locator(sel).first.is_visible(timeout=200):
                return "puzzle"
        except:
            pass
            
    # Check Captcha
    for sel in AMAZON_SELECTORS["interstitials"]["captcha"]:
        try:
            if page.locator(sel).first.is_visible(timeout=200):
                return "captcha"
        except:
            pass
            
    # Check Passkey
    if "/claim/webauthn/nudge" in page.url.lower():
        return "passkey_nudge"
        
    for sel in AMAZON_SELECTORS["interstitials"]["passkey"]:
        try:
            if page.locator(sel).first.is_visible(timeout=200):
                return "passkey_nudge"
        except:
            pass
            
    return None


def _detect_verification(page) -> str | None:
    """Check for OTP, Mobile Add, etc. But PUZZLE takes priority!"""
    
    url = page.url.lower()
    
    # ============================================================
    # 🔑 CRITICAL: Check for PUZZLE first even on /ap/cvf URLs!
    # The puzzle page is at /ap/cvf/request?arb=... and has
    # "Solve this puzzle" text. We must detect it BEFORE verification.
    # ============================================================
    if "/ap/cvf" in url and "arb=" in url:
        # This could be puzzle OR verification - check content
        try:
            # Puzzle indicators - use :has-text() for partial matching
            puzzle_indicators = [
                ":has-text('Solve this puzzle')",
                ":has-text('Choose all')",
                ":has-text('Solved:')",
                "button:has-text('Confirm')",
                "img[src*='challenge']",
            ]
            for indicator in puzzle_indicators:
                try:
                    if page.locator(indicator).first.is_visible(timeout=300):
                        logger.debug(f"Detected PUZZLE via indicator: {indicator}")
                        return "puzzle"
                except:
                    pass
        except:
            pass
        
        # If no puzzle indicators found, check for actual OTP/verification content
        try:
            otp_indicators = [
                "text='Enter the code'",
                "text='Enter security code'", 
                "input[name='code']",
                "#cvf-input-code",
            ]
            for indicator in otp_indicators:
                try:
                    if page.locator(indicator).first.is_visible(timeout=300):
                        return "verification"
                except:
                    pass
        except:
            pass
        
        # Fallback: if /ap/cvf with arb= but no clear indicators, assume verification
        # (This is safer than assuming puzzle)
        return "verification"
    
    # ============================================================
    # 🔑 CHECK ADD_MOBILE BEFORE standard /ap/cvf check
    # The add_mobile page is at /ap/cvf/verify with "Add mobile number" text
    # ============================================================
    
    # Check for Add Mobile indicators FIRST
    for sel in AMAZON_SELECTORS["verification"]["add_mobile"]:
        try:
            if page.locator(sel).first.is_visible(timeout=300):
                logger.debug(f"Detected ADD_MOBILE via indicator: {sel}")
                return "add_mobile"
        except:
            pass
    
    # Standard /ap/cvf URL (no arb=) - return verification after add_mobile check
    if "/ap/cvf" in url or "verification" in url:
        return "verification"
    for sel in AMAZON_SELECTORS["verification"]["otp"]:
        try:
            if page.locator(sel).first.is_visible(timeout=200):
                return "verification"
        except:
            pass
            
    for sel in AMAZON_SELECTORS["verification"]["add_mobile"]:
        try:
            if page.locator(sel).first.is_visible(timeout=200):
                return "add_mobile"
        except:
            pass
            
    return None


def _detect_success(page) -> str | None:
    """Check for successful login/registration."""
    
    url = page.url.lower()
    for success_url in AMAZON_SELECTORS["success"]["urls"]:
        if success_url in url:
            return "success"
            
    # Check for specific "Hello, [Name]" header
    # But be careful not to mistake "Hello, Sign In" for success
    try:
        header_text = page.locator("#nav-link-accountList-nav-line-1").first.text_content()
        if header_text and "Hello," in header_text and "Sign in" not in header_text:
             return "success"
    except:
        pass
        
    return None


def _detect_core_flow(page) -> str | None:
    """Check for registration forms, signin choices, etc."""
    
    # Registration Form (Most specific)
    # Check detection via multiple overlapping signals
    reg_signals = 0
    if "/ap/register" in page.url.lower():
        reg_signals += 2
    
    try:
        if page.locator("input[name='customerName']").first.is_visible(timeout=200):
            reg_signals += 2
        if page.locator("#ap_password_check").first.is_visible(timeout=200):
            reg_signals += 2
    except:
        pass
        
    if reg_signals >= 2:
        return "registration_form"
        
    # Signin Choice (Radio buttons / Create Account)
    for sel in AMAZON_SELECTORS["core"]["signin_choice"]:
        try:
            if page.locator(sel).first.is_visible(timeout=200):
                return "signin_choice"
        except:
            pass
            
    # New Customer Intent
    if "/ax/claim/intent" in page.url.lower():
        return "new_customer_intent"
    for sel in AMAZON_SELECTORS["core"]["new_customer_intent"]:
        try:
            if page.locator(sel).first.is_visible(timeout=200):
                return "new_customer_intent"
        except:
            pass

    # Email Entry (Fallback if nothing else matches)
    # Check this last as it's the most generic "signin" page
    if "/ap/signin" in page.url.lower():
        # Double check it's not actually a choice page we missed
        try:
            if page.locator("input[name='email']").first.is_visible(timeout=200):
                return "email_signin_entry"
        except:
            pass
            
    return None


def _detect_via_cache(page) -> str | None:
    """
    Check for characteristic elements using cached XPaths.
    This bypasses complex selector loops and AgentQL entirely.
    """
    # Characteristic elements for each state
    state_keys = {
        "puzzle": "captcha_frame", # We often cache the frame for puzzle/captcha
        "captcha": "captcha_button",
        "verification": "otp_input",
        "add_mobile": "mobile_input",
        "registration_form": "registration_name_input",
        "signin_choice": "create_account_option",
        "new_customer_intent": "intent_proceed_button",
        "email_signin_entry": "login_email_input"
    }

    p_cache = {}
    try:
        from amazon.agentql_helper import _load_persistent_cache
        p_cache = _load_persistent_cache()
    except:
        return None

    for state, cache_key in state_keys.items():
        if cache_key in p_cache:
            try:
                # Characteristic elements should be visible if we are on that page
                xpath = p_cache[cache_key].get('xpath')
                if xpath:
                    locator = page.locator(f"xpath={xpath}").first
                    if locator.is_visible(timeout=300):
                        return state
            except:
                continue
    
    return None


def _detect_via_agentql(page, agentql_page) -> str | None:
    """
    Fallback detection using AgentQL and populate the cache.
    """
    try:
        logger.info("Using AgentQL for state detection fallback...")
        # Broad detection query
        query = """
        {
            captcha_frame
            puzzle_frame
            otp_input
            registration_form {
                name_input
                email_input
                password_input
            }
            create_account_option
            intent_proceed_button
            login_email_input
            payment_page {
                formatted_price(the price of the book/item)
                add_card_header(text like 'Add a credit or debit card')
            }
        }
        """
        response = agentql_page.query_elements(query)
        
        # Determine state and cache characteristic elements
        if response.captcha_frame or response.puzzle_frame:
            # We don't cache frames directly as elements often, but we can store the xpath
            return "puzzle" if response.puzzle_frame else "captcha"
            
        if response.otp_input:
            from amazon.agentql_helper import query_and_extract
            # We dummy query to cache the xpath
            query_and_extract(page, "{ otp_input }", "otp_input")
            return "verification"
            
        if response.registration_form.name_input:
            from amazon.agentql_helper import query_and_extract
            query_and_extract(page, "{ registration_form { name_input email_input } }", "registration_form")
            return "registration_form"
            
        if response.create_account_option:
            from amazon.agentql_helper import query_and_extract
            query_and_extract(page, "{ create_account_option }", "signin_page")
            return "signin_choice"
            
        if response.intent_proceed_button:
            from amazon.agentql_helper import query_and_extract
            query_and_extract(page, "{ intent_proceed_button }", "intent_page")
            return "new_customer_intent"
            
        if response.login_email_input:
            from amazon.agentql_helper import query_and_extract
            query_and_extract(page, "{ login_email_input }", "email_signin")
            return "email_signin_entry"

        if response.payment_page.formatted_price or response.payment_page.add_card_header:
            logger.success("✅ Detected Payment Page via AgentQL")
            return "success"
            
    except Exception as e:
        logger.debug(f"State detection via AgentQL failed: {e}")
        
    return None


def _is_network_error(page) -> bool:
    """Detect if we are on a browser error page."""
    try:
        # Check for specific network error codes in title or body
        title = page.title().lower()
        if "site can't be reached" in title or "error" in title or "amazon.com.au" in title:
             if "amazon.com" not in title and len(page.content()) < 1000:
                # Likely an error page with just URL in title
                return True
        
        # Check for common error page elements (Chromium)
        error_indicators = [
            "#main-frame-error",
            "#diagnose-button",
            "text=ERR_TUNNEL_CONNECTION_FAILED",
            "text=ERR_CONNECTION_REFUSED",
            "text=ERR_NAME_NOT_RESOLVED",
            "text=ERR_CONNECTION_TIMED_OUT"
        ]
        for sel in error_indicators:
            try:
                if page.locator(sel).first.is_visible(timeout=200):
                    return True
            except: pass
        
        # Check for empty/blank page content
        content = page.content()
        if len(content) < 300 and "<html><head></head><body>" in content.lower():
            return True
            
    except Exception as e:
        err_msg = str(e).lower()
        # SecurityError: Failed to read 'localStorage' often means we are on a browser-internal/error page
        if "access is denied" in err_msg or "securityerror" in err_msg:
            return True
        pass
    return False
