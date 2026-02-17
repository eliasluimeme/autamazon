"""
Outlook Setup Flow Encapsulation
"""
from loguru import logger
from amazon.identity_manager import Identity

def handle_outlook_setup(manager, page, device):
    """
    Handles the Outlook signup process and transitions to Amazon.
    
    Args:
        manager: OpSecBrowserManager instance
        page: Current playwright page
        device: DeviceAdapter instance
        
    Returns:
        tuple: (identity, new_page) if successful, (None, None) if failed
    """
    logger.info("📧 Starting Outlook Signup Step...")
    
    max_attempts = 3
    for attempt in range(max_attempts):
        logger.info(f"📧 Outlook Signup Attempt {attempt + 1}/{max_attempts}")
        
        try:
            from amazon.outlook.run import run_outlook_signup
            outlook_data = run_outlook_signup(page, device)
            
            if outlook_data == "RETRY":
                logger.warning(f"🔄 Outlook signaled retry (Attempt {attempt + 1})")
                if attempt < max_attempts - 1:
                    # Clean up/Restart page
                    page.goto("about:blank")
                    time.sleep(2)
                    page.goto("https://signup.live.com/signup?lic=1")
                    continue
                else:
                    logger.error("❌ Max Outlook retries reached")
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
                
                # Open new tab for Amazon
                logger.info("Opening new tab for Amazon...")
                new_page = manager.context.new_page()
                
                return generated_identity, new_page
                
            else:
                logger.error("Outlook signup failed (no data returned)")
                return None, None
                
        except Exception as e:
            logger.error(f"Outlook step failed on attempt {attempt + 1}: {e}")
            if attempt < max_attempts - 1:
                continue
            return None, None
            
    return None, None
