"""
Outlook Setup Flow Encapsulation
"""
import time
from loguru import logger
from amazon.identity_manager import Identity

def handle_outlook_setup(manager, page, device):
    """
    Handles the Outlook signup process and transitions to Amazon.
    """
    logger.info("📧 Starting Outlook Signup Step...")
    
    # User Request: Use a new tab and close the old one
    try:
        logger.info("🆕 Switching to fresh tab for Outlook...")
        new_outlook_page = manager.context.new_page()
        if page and not page.is_closed():
            page.close()
        page = new_outlook_page
        device.page = page
    except Exception as e:
        logger.warning(f"Could not recycle tab for Outlook: {e}")
    
    max_attempts = 3
    for attempt in range(max_attempts):
        logger.info(f"📧 Outlook Signup Attempt {attempt + 1}/{max_attempts}")
        
        try:
            if page.is_closed():
                page = manager.context.new_page()
                device.page = page

            from amazon.outlook.run import run_outlook_signup
            outlook_data = run_outlook_signup(page, device)
            
            if outlook_data == "RETRY":
                logger.warning(f"🔄 Outlook signaled retry (Attempt {attempt + 1})")
                if attempt < max_attempts - 1:
                    time.sleep(2)
                    continue
                else:
                    return None, None
            
            if outlook_data and isinstance(outlook_data, dict):
                logger.success(f"✓ Outlook signup successful: {outlook_data.get('email_handle')}@outlook.com")
                
                # Create Identity object for Amazon flow
                generated_identity = Identity(
                    firstname=outlook_data['firstname'],
                    lastname=outlook_data['lastname'],
                    email=f"{outlook_data['email_handle']}@outlook.com",
                    password=outlook_data['password']
                )
                
                # Open new tab for Amazon and close Outlook tab
                logger.info("🚀 Transitioning to Amazon in a fresh tab...")
                final_page = manager.context.new_page()
                page.close()
                
                return generated_identity, final_page
                
            else:
                logger.error("Outlook signup failed (no data returned)")
                if attempt < max_attempts - 1:
                    continue
                return None, None
                
        except Exception as e:
            logger.error(f"Outlook step failed on attempt {attempt + 1}: {e}")
            if attempt < max_attempts - 1:
                time.sleep(2)
                continue
            return None, None
            
    return None, None
