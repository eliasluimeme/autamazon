"""
Outlook Login Orchestration
Main entry point for the Outlook login module.
"""

import time
from loguru import logger
import agentql

from amazon.outlook_login.config import (
    OUTLOOK_LOGIN_URL,
    MAX_DURATION,
    DELAYS
)

from amazon.outlook_login.actions.detect import detect_current_step
from amazon.outlook_login.actions.email import handle_email_step
from amazon.outlook_login.actions.password import handle_password_step
from amazon.outlook_login.actions.skip import handle_skip_step
from amazon.outlook_login.actions.stay_signed_in import handle_stay_signed_in_step

def run_outlook_login(page, device, identity: dict):
    """
    Run the full Outlook login flow.
    
    Args:
        page: Playwright page object
        device: DeviceAdapter instance
        identity: dictated identity with credentials
        
    Returns:
        dict: Identity with credentials if successful, None otherwise
    """
    logger.info("🚀 Starting Outlook Login Flow")
    
    # Navigate to Login
    logger.info(f"Navigating to {OUTLOOK_LOGIN_URL}...")
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

            page.goto(OUTLOOK_LOGIN_URL, wait_until="domcontentloaded", timeout=45000)
            success_nav = True
            break
        except Exception as e:
            err_msg = str(e).lower()
            logger.warning(f"Outlook login navigation attempt {attempt+1} failed: {e}")
            if "target page, context or browser has been closed" in err_msg or "target closed" in err_msg:
                time.sleep(3)
                continue
            time.sleep(5)
            
    if not success_nav:
        logger.error("Failed to navigate to Outlook login after multiple attempts.")
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
        current_step = detect_current_step(page, agentql_page)
        
        if current_step != previous_step:
            logger.info(f"📍 Detected Login Step: {current_step}")
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
            
        elif current_step == "SKIP":
            success = handle_skip_step(page, device, agentql_page)
            
        elif current_step == "STAY_SIGNED_IN":
            success = handle_stay_signed_in_step(page, device, agentql_page)
            
        elif current_step == "ERROR":
            error_count = state_retry_counts.get("ERROR", 0)
            
            if error_count < 2:
                logger.warning(
                    f"🛑 Error page detected (attempt {error_count + 1}/2). "
                    f"Closing tab and opening fresh one..."
                )
                try:
                    previous_step = "ERROR"
                    # Close broken tab, open a fresh one
                    context = page.context
                    if not page.is_closed():
                        page.close()
                    page = context.new_page()
                    device.page = page
                    # Re-wrap AgentQL
                    try:
                        agentql_page = agentql.wrap(page)
                    except Exception:
                        agentql_page = None
                    # Navigate fresh
                    page.goto(OUTLOOK_LOGIN_URL, wait_until="domcontentloaded", timeout=45000)
                    time.sleep(DELAYS["page_load"][0])
                    logger.info("✅ Fresh tab opened and navigated to login.")
                    continue
                except Exception as e:
                    logger.error(f"Tab recycle failed: {e}")
            
            logger.error("🛑 Outlook error page persists after tab recycle. Requesting full retry...")
            return "RETRY"
            
        elif current_step == "SUCCESS":
            logger.success(f"🎉 Outlook Login Successful: {identity.get('email_handle', identity.get('email', 'Unknown'))}")
            return identity
            
        elif current_step == "UNKNOWN":
            logger.debug("Unknown state, waiting...")
            time.sleep(2)
            
        # Loop throttling
        time.sleep(1)
        previous_step = current_step
        
    logger.error("Outlook login timed out")
    return None
