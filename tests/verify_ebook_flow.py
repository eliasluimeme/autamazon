import sys
import os
from loguru import logger

# Configure paths
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../social-ui')))

from modules.opsec_workflow import OpSecBrowserManager
from amazon.device_adapter import DeviceAdapter
from amazon.element_locator import ElementLocator
from amazon.actions.ebook_search_flow import run_ebook_search_flow

def verify_ebook_flow(profile_id: str):
    manager = OpSecBrowserManager(profile_id)
    try:
        logger.info(f"Starting verification for profile: {profile_id}")
        manager.start_browser(headless=False)
        playwright_page = manager.context.new_page()
        
        device = DeviceAdapter(playwright_page)
        locator = ElementLocator(playwright_page, device.device_type)
        
        if run_ebook_search_flow(playwright_page, device, locator):
            logger.success("✓ Ebook search flow completed successfully!")
            logger.info(f"Final URL: {playwright_page.url}")
        else:
            logger.error("❌ Ebook search flow failed")
            
    except Exception as e:
        logger.error(f"Verification failed: {e}")
    finally:
        # Keep browser open for a bit to see result
        import time
        time.sleep(10)
        manager.stop_browser()

if __name__ == "__main__":
    if len(sys.argv) < 2:
        logger.error("Usage: python amazon/tests/verify_ebook_flow.py <PROFILE_ID>")
        sys.exit(1)
    verify_ebook_flow(sys.argv[1])
