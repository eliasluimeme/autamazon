"""
CAPTCHA Solver for Amazon Automation

Integrates with 2captcha service to solve:
- Image-based CAPTCHAs (distorted text)
- Amazon WAF CAPTCHAs

Requires:
- pip install 2captcha-python
- TWOCAPTCHA_API_KEY environment variable
"""

import os
import time
import base64
from loguru import logger

try:
    from twocaptcha import TwoCaptcha
    TWOCAPTCHA_AVAILABLE = True
except ImportError:
    TWOCAPTCHA_AVAILABLE = False
    logger.warning("2captcha-python not installed. CAPTCHA solving disabled.")


# Initialize solver with API key
TWOCAPTCHA_API_KEY = os.getenv("TWOCAPTCHA_API_KEY", "")

if TWOCAPTCHA_AVAILABLE and TWOCAPTCHA_API_KEY:
    solver = TwoCaptcha(TWOCAPTCHA_API_KEY)
else:
    solver = None


def is_captcha_present(page) -> dict:
    """
    Detect if a CAPTCHA is present on the page.
    
    Returns:
        dict with 'present': bool, 'type': str, 'element': locator
    """
    result = {
        'present': False,
        'type': None,
        'element': None,
        'image_url': None,
    }
    
    try:
        # Check for Amazon puzzle CAPTCHA
        puzzle_selectors = [
            "#captcha-image",
            "img[alt*='captcha']",
            "img[src*='captcha']",
            ".captcha-image",
            "#auth-captcha-guess-box",  # Amazon captcha input
        ]
        
        for selector in puzzle_selectors:
            try:
                element = page.locator(selector).first
                if element.is_visible(timeout=1000):
                    result['present'] = True
                    result['type'] = 'image'
                    result['element'] = element
                    
                    # Try to get image URL
                    if 'img' in selector:
                        result['image_url'] = element.get_attribute('src')
                    
                    logger.info(f"CAPTCHA detected: {result['type']}")
                    return result
            except:
                continue
        
        # Check for "Enter the characters you see" text
        try:
            if page.locator("text=characters you see").first.is_visible(timeout=500):
                result['present'] = True
                result['type'] = 'image'
                # Find the captcha image nearby
                img = page.locator("img[src*='captcha']").first
                if img.is_visible(timeout=500):
                    result['element'] = img
                    result['image_url'] = img.get_attribute('src')
        except:
            pass
        
        # Check for Amazon "I'm not a robot" verification or Arkose puzzle
        try:
            if (page.locator("text=I'm not a robot").first.is_visible(timeout=500) or
                page.locator("text=Solve this puzzle").first.is_visible(timeout=500) or
                page.locator("text=Choose all").first.is_visible(timeout=500) or
                page.locator("button:has-text('Confirm')").first.is_visible(timeout=500)):
                result['present'] = True
                result['type'] = 'checkbox' # Treat complex puzzle as manual checkbox for now
        except:
            pass
            
    except Exception as e:
        logger.debug(f"CAPTCHA detection error: {e}")
    
    return result


def solve_image_captcha(page, captcha_info: dict) -> str:
    """
    Solve an image-based CAPTCHA using 2captcha.
    
    Args:
        page: Playwright page
        captcha_info: Dict from is_captcha_present()
        
    Returns:
        Solved captcha text or None
    """
    if not solver:
        logger.error("2captcha solver not available")
        return None
    
    try:
        image_url = captcha_info.get('image_url')
        
        if image_url:
            # If URL is relative, make it absolute
            if image_url.startswith('/'):
                base_url = page.url.split('/')[0:3]
                image_url = '/'.join(base_url) + image_url
            
            logger.info(f"Sending captcha to 2captcha: {image_url[:50]}...")
            
            # Solve using URL
            result = solver.normal(image_url)
            captcha_code = result.get('code')
            
            if captcha_code:
                logger.success(f"CAPTCHA solved: {captcha_code}")
                return captcha_code
        else:
            # Take screenshot of captcha element and solve from image
            element = captcha_info.get('element')
            if element:
                screenshot_bytes = element.screenshot()
                screenshot_b64 = base64.b64encode(screenshot_bytes).decode('utf-8')
                
                logger.info("Sending captcha screenshot to 2captcha...")
                result = solver.normal(screenshot_b64, numeric=0, minLength=4, maxLength=8)
                captcha_code = result.get('code')
                
                if captcha_code:
                    logger.success(f"CAPTCHA solved: {captcha_code}")
                    return captcha_code
                    
    except Exception as e:
        logger.error(f"CAPTCHA solving failed: {e}")
    
    return None


def enter_captcha_solution(page, solution: str, device=None) -> bool:
    """
    Enter the solved CAPTCHA into the input field.
    
    Args:
        page: Playwright page
        solution: Solved captcha text
        device: DeviceAdapter instance
        
    Returns:
        True if entered successfully
    """
    captcha_input_selectors = [
        "#captchacharacters",
        "#auth-captcha-guess",
        "input[name='captchacharacters']",
        "input[name='cvf_captcha_captcha_token']",
        "input[placeholder*='characters']",
    ]
    
    for selector in captcha_input_selectors:
        try:
            element = page.locator(selector).first
            if element.is_visible(timeout=1000):
                element.fill("")  # Clear first
                time.sleep(0.3)
                
                if device:
                    device.type_text(element, solution, "captcha input")
                else:
                    element.type(solution, delay=50)
                
                logger.info(f"Entered CAPTCHA solution: {solution}")
                return True
        except:
            continue
    
    logger.warning("Could not find CAPTCHA input field")
    return False


def handle_captcha(page, device=None, max_attempts: int = 3) -> bool:
    """
    Main function to detect and solve CAPTCHA.
    
    Args:
        page: Playwright page
        device: DeviceAdapter instance
        max_attempts: Maximum solve attempts
        
    Returns:
        True if CAPTCHA was solved and submitted
    """
    for attempt in range(max_attempts):
        logger.info(f"CAPTCHA handling attempt {attempt + 1}/{max_attempts}")
        
        # Detect CAPTCHA
        captcha_info = is_captcha_present(page)
        
        if not captcha_info['present']:
            logger.info("No CAPTCHA detected")
            return True  # No captcha = success
        
        if captcha_info['type'] == 'image':
            # Solve image captcha
            solution = solve_image_captcha(page, captcha_info)
            
            if solution:
                # Enter solution
                if enter_captcha_solution(page, solution, device):
                    time.sleep(0.5)
                    
                    # Click submit/continue button
                    submit_selectors = [
                        "button[type='submit']",
                        "input[type='submit']",
                        "#continue",
                        ".a-button-input",
                    ]
                    
                    for selector in submit_selectors:
                        try:
                            btn = page.locator(selector).first
                            if btn.is_visible(timeout=500):
                                btn.click()
                                logger.info("Clicked submit after CAPTCHA")
                                time.sleep(2)
                                break
                        except:
                            continue
                    
                    # Check if CAPTCHA is gone
                    time.sleep(2)
                    new_info = is_captcha_present(page)
                    if not new_info['present']:
                        logger.success("✓ CAPTCHA solved successfully")
                        return True
                    else:
                        logger.warning("CAPTCHA still present, retrying...")
            else:
                logger.warning("Failed to get CAPTCHA solution")
        
        elif captcha_info['type'] == 'checkbox':
            # Simple checkbox - just click it
            try:
                page.locator("text=I'm not a robot").first.click()
                time.sleep(2)
                logger.info("Clicked 'I'm not a robot' checkbox")
            except:
                pass
        
        time.sleep(1)
    
    logger.error(f"Failed to solve CAPTCHA after {max_attempts} attempts")
    return False
