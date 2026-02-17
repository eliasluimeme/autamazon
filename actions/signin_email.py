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
    
    # Priority 1: CSS Selectors (fastest - Amazon selectors are stable)
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
                break
        except:
            continue
    
    if email_input:
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
                    break
            except:
                continue
    
    # Priority 2: Cached XPaths -> AgentQL (only if CSS failed)
    if email_input is None:
        logger.info("🔄 CSS failed, trying AgentQL...")
        results = query_amazon(page, "signin_page", cache=True)
        
        if results and 'email_input' in results:
            email_input = results['email_input']['element']
            if 'continue_button' in results:
                continue_btn = results['continue_button']['element']
    
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
        if continue_btn:
            logger.info("Clicking Continue button...")
            
            initial_url = page.url
            device.tap(continue_btn, "Continue button")
            
            # Verify progression
            time.sleep(2)
            if page.url != initial_url:
                logger.success("✅ Email entered and Continue clicked!")
                return True
        
        return True # Assume success if no error thrown
        
    except Exception as e:
        logger.error(f"Failed to handle email signin step: {e}")
        return False
