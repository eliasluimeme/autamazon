"""
Signin Email Entry Handler for Amazon Automation

Handles the "Sign in or create account" page that appears after Buy Now:
- Detects the email entry page
- Enters email from identity
- Clicks Continue button
- Uses self-healing XPath caching (via agentql_helper) for resilience
"""

import time
import random
from loguru import logger

from amazon.config import DELAYS
from amazon.device_adapter import DeviceAdapter
from amazon.agentql_helper import query_amazon
from amazon.utils.xpath_cache import get_cached_xpath, extract_and_cache_xpath


def is_email_signin_page(page) -> bool:
    """
    Detect if we're on the simple "Sign in or create account" email entry page.
    """
    try:
        url = page.url.lower()
        if "/ap/signin" not in url:
            return False
            
        # Check for choice indicators (Variant 1) - if these exist, it's NOT a simple entry page
        choice_indicators = [
            "input[name='create'][type='radio']",
            "#createAccountSubmit",
            "button:has-text('Create account')",
        ]
        for indicator in choice_indicators:
            if page.locator(indicator).first.is_visible(timeout=300):
                return False

        # Check for email input
        if page.locator("#ap_email").first.is_visible(timeout=500) or \
           page.locator("input[name='email']").first.is_visible(timeout=500):
            return True
                
    except Exception as e:
        logger.debug(f"Email signin page detection error: {e}")
    
    return False


def handle_email_signin_step(page, identity, device: DeviceAdapter = None) -> bool:
    """
    Handle the email signin entry step using a 3-priority approach.
    Priority: CSS Selectors (fastest) -> Cached XPaths -> AgentQL (slowest)
    """
    if device is None:
        device = DeviceAdapter(page)
    
    # Get email from identity
    email = identity.get('email', '') if isinstance(identity, dict) else getattr(identity, 'email', str(identity))
    if not email:
        logger.error("No email available from identity")
        return False
    
    logger.info(f"📧 Handling SIGNIN EMAIL step for: {email}")
    
    email_input = None
    continue_btn = None
    
    # Priority 0: Cached XPaths (Fastest and resilient)
    logger.debug("Checking for cached XPaths...")
    try:
        cached_email_xpath = get_cached_xpath("signin_email_input")
        if cached_email_xpath:
            loc = page.locator(f"xpath={cached_email_xpath}").first
            if loc.is_visible(timeout=500):
                email_input = loc
                logger.info("✅ Found email input via cached XPath")
                
        cached_continue_xpath = get_cached_xpath("signin_continue_btn")
        if cached_continue_xpath:
            loc = page.locator(f"xpath={cached_continue_xpath}").first
            if loc.is_visible(timeout=500):
                continue_btn = loc
                logger.info("✅ Found continue button via cached XPath")
    except Exception as e:
        logger.debug(f"XPath cache error: {e}")
        
    # Priority 1: CSS Selectors (fastest - Amazon selectors are stable)
    if email_input is None:
        logger.debug("Trying CSS selectors first...")
        email_selectors = [
            "#ap_email",
            "input[name='email']",
            "input[type='email']",
        ]
        for sel in email_selectors:
            try:
                loc = page.locator(sel).first
                if loc.is_visible(timeout=1000):
                    email_input = loc
                    logger.debug(f"Found email input via: {sel}")
                    try:
                        extract_and_cache_xpath(page, email_input, "signin_email_input")
                    except:
                        pass
                    break
            except:
                continue
    
    if continue_btn is None and email_input is not None:
        # Find continue button via CSS too
        continue_selectors = [
            "#continue",
            "input[id='continue']",
            "button:has-text('Continue')",
            "input[type='submit'][value='Continue']",
        ]
        for sel in continue_selectors:
            try:
                loc = page.locator(sel).first
                if loc.is_visible(timeout=500):
                    continue_btn = loc
                    logger.debug(f"Found continue button via: {sel}")
                    try:
                        extract_and_cache_xpath(page, continue_btn, "signin_continue_btn")
                    except:
                        pass
                    break
            except:
                continue
    
    # Priority 2: Cached XPaths -> AgentQL (only if CSS failed)
    if email_input is None or continue_btn is None:
        logger.info("🔄 CSS failed, trying AgentQL...")
        results = query_amazon(page, "signin_page", cache=True)
        
        if results and results.get('email_input') and results['email_input'].get('element'):
            if email_input is None:
                email_input = results['email_input']['element']
                try:
                    extract_and_cache_xpath(page, email_input, "signin_email_input")
                except:
                    pass
                
        if results and results.get('continue_button') and results['continue_button'].get('element'):
            if continue_btn is None:
                continue_btn = results['continue_button']['element']
                try:
                    extract_and_cache_xpath(page, continue_btn, "signin_continue_btn")
                except:
                    pass
    
    if email_input is None:
        logger.error("Could not find email input elements")
        return False
    
    try:
        # 1. Fill Email
        logger.info(f"Typing email...")
        email_input.fill("")
        time.sleep(0.2)
        device.type_text(email_input, email, "email")
        
        time.sleep(random.uniform(0.5, 1.0))
        
        # 2. Click Continue
        initial_url = page.url
        
        def has_progressed():
            if page.url != initial_url:
                return True
            # Check for password field
            try:
                if page.locator("input[name='password'], #ap_password").first.is_visible(timeout=500):
                    return True
            except Exception as e:
                # If we get a query error, it often means the page has navigated and the tree is gone/rebuilding, which is progression.
                if "Can't query n-th element" in str(e) or "navigating" in str(e).lower():
                    # We can assume it progressed if the page is literally tearing down the DOM
                    return True
                pass
                
            # Check if it transitioned to any typical subsequent page OR error notification inline
            progress_indicators = [
                "#createAccountSubmit",
                "#auth-create-account-link",
                "#ap_customer_name",
                "text='We cannot find an account'",
                "text='Cannot find account'",
                "button:has-text('Create account')",
                "text='We are sorry'",
                "text='Enter the characters'",
                "text='Please enter a valid email address'",
            ]
            for sel in progress_indicators:
                try:
                    if page.locator(sel).first.is_visible(timeout=200):
                        return True
                except:
                    pass
            return False

        logger.info("Attempting to submit form (Enter -> Click -> JS)...")
        # Step 2a: Press Enter inside the input field (Fastest, organic)
        try:
            email_input.press("Enter", timeout=1500)
            time.sleep(2)
        except Exception as e:
            logger.debug(f"Pressing Enter failed: {e}")
            
        if has_progressed():
            logger.success("✅ Email entered and advanced via Enter key!")
            return True

        # Step 2b: Standard explicit clicks
        if continue_btn:
            try:
                # Standard click (important for blur/change validation)
                continue_btn.click(timeout=3000)
                time.sleep(2)
            except:
                try:
                    continue_btn.click(force=True, timeout=1500)
                    time.sleep(2)
                except:
                    device.js_click(continue_btn, "Continue button")
                    time.sleep(2)
            
            if has_progressed():
                logger.success("✅ Email entered and Continue clicked natively!")
                return True
                
        # JS Fallback Click
        logger.warning("Continue button standard click didn't navigate, trying JS fallback on page...")
        result = page.evaluate("""
            () => {
                const submitBtns = document.querySelectorAll('input[type="submit"], button[type="submit"], #continue');
                for (const btn of submitBtns) {
                    if (btn.offsetParent !== null) {
                        btn.click();
                        return 'clicked_submit';
                    }
                }
                const form = document.querySelector('form');
                if (form) {
                    const submit = form.querySelector('input[type="submit"]');
                    if (submit && submit.offsetParent !== null) {
                        submit.click();
                        return 'clicked_form_submit';
                    }
                }
                return null;
            }
        """)
        if result:
            logger.info(f"JS fallback click executed: {result}")
            time.sleep(2)
            if has_progressed():
                logger.success("✅ Email entered and Continue clicked via JS fallback!")
                return True
                
        logger.error("❌ Failed to navigate past email entry step. Button click didn't trigger state change.")
        return False

        
    except Exception as e:
        logger.error(f"Failed to handle email signin step: {e}")
        return False
