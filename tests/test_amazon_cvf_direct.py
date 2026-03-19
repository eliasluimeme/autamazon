"""
Direct test for Amazon CVF CAPTCHA via provided URL.
"""

import time
import os
import sys
from dotenv import load_dotenv
from patchright.sync_api import sync_playwright
from loguru import logger

# Add root to sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

load_dotenv()
from captcha_solver import solve_captcha

def test_amazon_cvf_direct(url: str):
    """Test against a specific Amazon CVF puzzle URL."""
    with sync_playwright() as p:
        # Launch with some human-like arguments
        browser = p.chromium.launch(
            headless=False,
            args=["--disable-blink-features=AutomationControlled"]
        )
        context = browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
        page = context.new_page()

        logger.info(f"🧪 Test: Amazon CVF Direct URL")
        logger.info(f"🔗 URL: {url}")
        
        try:
            page.goto(url, wait_until="networkidle")
            time.sleep(2) # Wait for puzzle to render
            
            success = solve_captcha(page)
            
            if success:
                logger.success("✅ CAPTCHA SOLVE COMPLETED")
            else:
                logger.error("❌ CAPTCHA SOLVE FAILED")
                
        except Exception as e:
            logger.error(f"Test crashed: {e}")
        finally:
            logger.info("Test finished. Keeping browser open for 10s...")
            time.sleep(10)
            browser.close()

if __name__ == "__main__":
    # Ensure manual fallback is on for testing
    os.environ["CAPTCHA_MANUAL_FALLBACK"] = "True"
    
    target_url = "https://www.amazon.com/ap/cvf/request?arb=d6c72504-67ea-4037-a1ab-5f525d5c2f2d&language=en_US"
    if len(sys.argv) > 1:
        target_url = sys.argv[1]
        
    test_amazon_cvf_direct(target_url)
