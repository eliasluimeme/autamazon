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
    try:
        page.goto(OUTLOOK_SIGNUP_URL, wait_until="domcontentloaded", timeout=30000)
    except Exception as e:
        logger.error(f"Failed to navigate to Outlook signup: {e}")
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
            logger.error("🛑 Outlook error page detected. Requesting retry...")
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

