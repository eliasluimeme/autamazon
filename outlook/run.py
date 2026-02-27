"""
Outlook Signup Orchestration

Main entry point for the Outlook signup module.
Orchestrates the flow using modular action handlers.
"""

import time
from loguru import logger
import agentql

from amazon.outlook.config import (
    OUTLOOK_SIGNUP_URL,
    MAX_DURATION,
    DELAYS
)
from amazon.outlook.identity import generate_outlook_identity
from amazon.outlook.actions import (
    detect_current_step,
    handle_email_step,
    handle_password_step,
    handle_name_step,
    handle_dob_step,
    handle_captcha_step,
    handle_privacy_step,
    handle_passkey_step,
    handle_stay_signed_in_step
)

def run_outlook_signup(page, device):
    """
    Run the full Outlook signup flow.
    
    Args:
        page: Playwright page object
        device: DeviceAdapter instance
        
    Returns:
        dict: Identity with credentials if successful, None otherwise
    """
    logger.info("🚀 Starting Outlook Signup Flow")
    
    # Generate Identity
    identity = generate_outlook_identity(country_code="US")
    
    # Navigate to Signup
    logger.info(f"Navigating to {OUTLOOK_SIGNUP_URL}...")
    success_nav = False
    for attempt in range(3):
        try:
            if page.is_closed():
                logger.warning("Tab was closed unexpectedly. Attempting to recover...")
                # Try to get a new page from the same context if possible
                try:
                    page = page.context.new_page()
                    device.page = page
                    # Re-wrap if needed
                    try: agentql_page = agentql.wrap(page)
                    except: pass
                except:
                    logger.error("Could not recover page context.")
                    return None

            page.goto(OUTLOOK_SIGNUP_URL, wait_until="domcontentloaded", timeout=45000)
            success_nav = True
            break
        except Exception as e:
            err_msg = str(e).lower()
            logger.warning(f"Outlook navigation attempt {attempt+1} failed: {e}")
            if "target page, context or browser has been closed" in err_msg or "target closed" in err_msg:
                time.sleep(3)
                continue
            time.sleep(5)
            
    if not success_nav:
        logger.error("Failed to navigate to Outlook signup after multiple attempts.")
        return None
        
    time.sleep(DELAYS["page_load"][0])
    
    # Initialize AgentQL (lazy wrap)
    try:
        agentql_page = agentql.wrap(page)
    except Exception:
        agentql_page = None
    
    # State Loop
    start_time = time.time()
    state_retry_counts = {}
    previous_step = None
    
    while time.time() - start_time < MAX_DURATION:
        # Detect Step
        current_step = detect_current_step(page, agentql_page)
        
        # Log step change
        if current_step != previous_step:
            logger.info(f"📍 Detected Step: {current_step}")
            state_retry_counts[current_step] = 0
        else:
            state_retry_counts[current_step] = state_retry_counts.get(current_step, 0) + 1
            
        # Handle Steps
        success = False
        
        if current_step == "EMAIL":
            success = handle_email_step(
                page, 
                identity, 
                device, 
                agentql_page, 
                retry_count=state_retry_counts[current_step]
            )
            # Update identity if rotated inside handler (handler modifies dict in-place)
            
        elif current_step == "PASSWORD":
            success = handle_password_step(page, identity, device, agentql_page)
            
        elif current_step == "NAME":
            success = handle_name_step(page, identity, device, agentql_page)
            
        elif current_step == "DOB":
            success = handle_dob_step(page, identity, device, agentql_page)
            
        elif current_step == "CAPTCHA":
            success = handle_captcha_step(page, device, agentql_page)
            
        elif current_step == "PASSKEY":
            success = handle_passkey_step(page, device, agentql_page)
            
        elif current_step == "PRIVACY":
            success = handle_privacy_step(page, device, agentql_page)
            
        elif current_step == "STAY_SIGNED_IN":
            success = handle_stay_signed_in_step(page, device, agentql_page)
            
        elif current_step == "ERROR":
            # User Request: If network error occurs, try reloading first before a full retry
            # However, if it's the specific errcode=100, we should restart immediately as requested
            url = page.url.lower()
            if "errcode=100" in url:
                logger.error("🛑 Outlook error 100 detected. Restarting signup flow...")
                return "RETRY"

            error_count = state_retry_counts.get("ERROR", 0)
            if error_count < 1:
                logger.warning("🛑 Network error detected. Attempting page reload...")
                try:
                    # Update previous_step before continuing to ensure retry count increments
                    previous_step = "ERROR" 
                    page.reload(wait_until="domcontentloaded", timeout=30000)
                    time.sleep(3)
                    continue # Re-detect state
                except Exception as e:
                    logger.error(f"Reload failed: {e}")
            
            logger.error("🛑 Outlook error page persists or reload failed. Requesting full retry...")
            return "RETRY"
            
        elif current_step == "SUCCESS":
            logger.success(f"🎉 Outlook Account Created: {identity['email_handle']}@outlook.com")
            # Save to file
            try:
                with open("created_hotmails.txt", "a") as f:
                    f.write(f"{identity['email_handle']}@outlook.com:{identity['password']}\n")
            except:
                pass
            return identity
            
        elif current_step == "UNKNOWN":
            logger.debug("Unknown state, waiting...")
            time.sleep(2)
            
        # Loop throttling
        time.sleep(1)
        previous_step = current_step
        
    logger.error("Outlook signup timed out")
    return None


def run_outlook_signup_with_identity(page, device, pre_generated_identity: dict):
    """
    Run Outlook signup with a PRE-GENERATED identity (V3 optimization).
    
    This variant skips the identity generation step entirely, using
    an identity that was pre-warmed by the IdentityPool before browser launch.
    
    The flow is identical to run_outlook_signup() except:
    - No call to generate_outlook_identity()
    - Identity is passed directly
    - ~3-5s faster startup per profile
    
    Args:
        page: Playwright page object
        device: DeviceAdapter instance
        pre_generated_identity: Dict with keys: firstname, lastname,
            email_handle, password, dob_month, dob_day, dob_year
        
    Returns:
        dict: Identity with credentials if successful, 
              "RETRY" for retry signal, None on failure
    """
    logger.info("🚀 Starting Outlook Signup Flow (pre-loaded identity)")
    
    # Use the pre-generated identity directly — no generation delay!
    identity = pre_generated_identity
    logger.info(
        f"🆔 Using pre-warmed identity: {identity['firstname']} {identity['lastname']} "
        f"({identity['email_handle']})"
    )
    
    # Navigate to Signup
    logger.info(f"Navigating to {OUTLOOK_SIGNUP_URL}...")
    success_nav = False
    for attempt in range(3):
        try:
            if page.is_closed():
                logger.warning("Tab was closed unexpectedly. Attempting to recover...")
                try:
                    page = page.context.new_page()
                    device.page = page
                    try: agentql_page = agentql.wrap(page)
                    except: pass
                except:
                    logger.error("Could not recover page context.")
                    return None

            page.goto(OUTLOOK_SIGNUP_URL, wait_until="domcontentloaded", timeout=45000)
            success_nav = True
            break
        except Exception as e:
            err_msg = str(e).lower()
            logger.warning(f"Outlook navigation attempt {attempt+1} failed: {e}")
            if "target page, context or browser has been closed" in err_msg or "target closed" in err_msg:
                time.sleep(3)
                continue
            time.sleep(5)
            
    if not success_nav:
        logger.error("Failed to navigate to Outlook signup after multiple attempts.")
        return None
        
    time.sleep(DELAYS["page_load"][0])
    
    # Initialize AgentQL (lazy wrap)
    try:
        agentql_page = agentql.wrap(page)
    except Exception:
        agentql_page = None
    
    # State Loop (identical to original)
    start_time = time.time()
    state_retry_counts = {}
    previous_step = None
    
    while time.time() - start_time < MAX_DURATION:
        current_step = detect_current_step(page, agentql_page)
        
        if current_step != previous_step:
            logger.info(f"📍 Detected Step: {current_step}")
            state_retry_counts[current_step] = 0
        else:
            state_retry_counts[current_step] = state_retry_counts.get(current_step, 0) + 1
            
        success = False
        
        if current_step == "EMAIL":
            success = handle_email_step(
                page, identity, device, agentql_page, 
                retry_count=state_retry_counts[current_step]
            )
        elif current_step == "PASSWORD":
            success = handle_password_step(page, identity, device, agentql_page)
        elif current_step == "NAME":
            success = handle_name_step(page, identity, device, agentql_page)
        elif current_step == "DOB":
            success = handle_dob_step(page, identity, device, agentql_page)
        elif current_step == "CAPTCHA":
            success = handle_captcha_step(page, device, agentql_page)
        elif current_step == "PASSKEY":
            success = handle_passkey_step(page, device, agentql_page)
        elif current_step == "PRIVACY":
            success = handle_privacy_step(page, device, agentql_page)
        elif current_step == "STAY_SIGNED_IN":
            success = handle_stay_signed_in_step(page, device, agentql_page)
        elif current_step == "ERROR":
            url = page.url.lower()
            if "errcode=100" in url:
                logger.error("🛑 Outlook error 100. Restarting signup flow...")
                return "RETRY"
            error_count = state_retry_counts.get("ERROR", 0)
            if error_count < 1:
                logger.warning("🛑 Network error. Attempting page reload...")
                try:
                    previous_step = "ERROR"
                    page.reload(wait_until="domcontentloaded", timeout=30000)
                    time.sleep(3)
                    continue
                except Exception as e:
                    logger.error(f"Reload failed: {e}")
            logger.error("🛑 Outlook error persists. Requesting full retry...")
            return "RETRY"
        elif current_step == "SUCCESS":
            logger.success(f"🎉 Outlook Account Created: {identity['email_handle']}@outlook.com")
            try:
                with open("created_hotmails.txt", "a") as f:
                    f.write(f"{identity['email_handle']}@outlook.com:{identity['password']}\n")
            except:
                pass
            return identity
        elif current_step == "UNKNOWN":
            logger.debug("Unknown state, waiting...")
            time.sleep(2)
            
        time.sleep(1)
        previous_step = current_step
        
    logger.error("Outlook signup timed out")
    return None

