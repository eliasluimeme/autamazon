
import os
import sys
import time
from dotenv import load_dotenv
from patchright.sync_api import sync_playwright
from loguru import logger

# Add root directory to path so we can import captcha_solver
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from captcha_solver import AmazonCaptchaSolver

load_dotenv()

def test_nopecha_audio():
    # 1. Check API Key
    nopecha_key = os.getenv("NOPECHA_API_KEY")
    if not nopecha_key:
        logger.error("NOPECHA_API_KEY not found in .env")
        return

    # 2. Test URL (from your .env sample)
    # Using one of the example URLs in the .env
    test_url = "https://www.amazon.com/ap/cvf/request?arb=70e8744e-8ea2-4447-8e78-8526cfb5383f&language=en_US"
    
    logger.info(f"🚀 Starting Nopecha Audio Test (SYNC) on: {test_url}")

    with sync_playwright() as p:
        # Launch browser (headless=False so you can see it)
        # Using slow_mo to make it easier to watch the switch
        browser = p.chromium.launch(headless=False, args=["--window-size=1280,1024"])
        context = browser.new_context(viewport={"width": 1280, "height": 1024})
        page = context.new_page()

        try:
            # Navigate to the CAPTCHA page
            logger.info("Navigating...")
            page.goto(test_url, timeout=60000)
            page.wait_for_load_state("networkidle")
            
            # Initialize Solver
            solver = AmazonCaptchaSolver(page)
            
            # Start Solve (should trigger Audio switch because it's first prioritized)
            logger.info("Starting Solver Loop...")
            success = solver.solve()
            
            if success:
                logger.success("✅ Nopecha Audio solving TEST PASSED!")
            else:
                logger.error("❌ Nopecha Audio solving TEST FAILED.")
                
            # Keep browser open for a few seconds to inspect
            logger.info("Closing in 10 seconds...")
            time.sleep(10)

        except Exception as e:
            logger.exception(f"Test encountered an error: {e}")
        finally:
            browser.close()

if __name__ == "__main__":
    test_nopecha_audio()
