"""
Test suite for AmazonCaptchaSolver

Tests:
  1. reCAPTCHA v2 demo site
  2. Amazon CVF simulation (via actual Amazon if available)
"""

import time
import os
from dotenv import load_dotenv
from patchright.sync_api import sync_playwright

load_dotenv()
from captcha_solver import solve_captcha
from loguru import logger


def test_recaptcha_demo():
    """Test against Google's reCAPTCHA v2 demo page."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page()

        logger.info("🧪 Test: reCAPTCHA v2 Demo")
        page.goto("https://recaptcha-demo.appspot.com/recaptcha-v2-checkbox.php")

        # Trigger the checkbox
        try:
            iframe = page.frame_locator('iframe[title="reCAPTCHA"]').first
            iframe.get_by_role("checkbox", name="I'm not a robot").click()
            time.sleep(2)
        except Exception as e:
            logger.error(f"Failed to trigger reCAPTCHA: {e}")

        success = solve_captcha(page)
        logger.success("✅ reCAPTCHA PASSED") if success else logger.error("❌ reCAPTCHA FAILED")

        time.sleep(3)
        browser.close()


def test_hcaptcha_demo():
    """Test against hCaptcha demo page."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page()

        logger.info("🧪 Test: hCaptcha Demo")
        page.goto("https://accounts.hcaptcha.com/demo")

        success = solve_captcha(page)
        logger.success("✅ hCaptcha PASSED") if success else logger.error("❌ hCaptcha FAILED")

        time.sleep(3)
        browser.close()


if __name__ == "__main__":
    os.environ["CAPTCHA_MANUAL_FALLBACK"] = "True"

    test_recaptcha_demo()
    # test_hcaptcha_demo()  # Uncomment to test hCaptcha

    logger.success("🏁 All tests completed.")
