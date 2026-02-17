"""
Email Verification Handler for Amazon Signup

Handles the OTP verification flow:
1. Detects CAPTCHA and prompts user to solve manually
2. Opens Outlook inbox in a new tab
3. Waits for Amazon verification email
4. Extracts the OTP code
5. Returns to Amazon tab and enters the code
"""

import time
import random
import re
from loguru import logger

from amazon.config import DELAYS


def handle_email_verification(browser_context, amazon_page, device, email: str, max_wait: int = 120) -> bool:
    """
    Handle the complete email verification flow.
    
    Args:
        browser_context: Playwright browser context (to create new tabs)
        amazon_page: The Amazon page waiting for OTP
        device: DeviceAdapter instance
        email: Email address to check for verification code
        max_wait: Maximum seconds to wait for email
        
    Returns:
        True if verification succeeded
    """
    logger.info("📧 Starting email verification flow...")
    
    # Step 0: Check for CAPTCHA first
    if _is_captcha_present(amazon_page):
        logger.warning("⚠️ CAPTCHA detected before OTP step!")
        if not _handle_captcha_manual(amazon_page, max_wait=300):
            logger.error("CAPTCHA not solved")
            return False
        # Re-check if we're now on OTP page
        time.sleep(2)
    
    # Verify we're on the OTP verification page
    if not _is_otp_page(amazon_page):
        logger.warning("Not on OTP verification page, checking URL...")
        url = amazon_page.url.lower()
        if "/ap/cvf" not in url and "verification" not in url:
            logger.error(f"Expected OTP page, got: {url}")
            return False
    
    # Step 1: Open Outlook in a new tab
    outlook_page = None
    try:
        outlook_page = browser_context.new_page()
        logger.info("📬 Opening Outlook inbox...")
        outlook_page.goto("https://outlook.live.com/mail/0/inbox", wait_until="domcontentloaded", timeout=30000)
        time.sleep(3)
        _wait_for_outlook_ready(outlook_page)
    except Exception as e:
        logger.error(f"Failed to open Outlook: {e}")
        if outlook_page: outlook_page.close()
        return False
    
    # Retry loop for OTP
    max_retries = 3
    used_otps = set()
    
    for attempt in range(max_retries):
        logger.info(f"🔄 OTP Attempt {attempt + 1}/{max_retries}")
        
        # Step 2: Buy time for email arrival
        if attempt > 0:
            logger.info("⏳ Waiting for fresh OTP email...")
            time.sleep(15)
            
        # Step 3: Get OTP
        otp_code = None
        try:
            # Refresh outlook on retries
            page_refreshed = False
            if attempt > 0:
                try:
                    outlook_page.reload()
                    _wait_for_outlook_ready(outlook_page)
                    page_refreshed = True
                except: pass
            
            # loop to ensure we get a NEW code
            otp_wait_start = time.time()
            while time.time() - otp_wait_start < (max_wait if attempt == 0 else 60):
                otp_code = _wait_for_amazon_email(outlook_page, device, 10) # short poll
                if otp_code and otp_code not in used_otps:
                    break
                elif otp_code in used_otps:
                    logger.info(f"Examples found ({otp_code}) but already used. Waiting for new one...")
                    if not page_refreshed and (time.time() - otp_wait_start) > 15:
                         try:
                            outlook_page.reload()
                            _wait_for_outlook_ready(outlook_page)
                            page_refreshed = True
                         except: pass
                    otp_code = None # Reset
                    time.sleep(5)
                else:
                    time.sleep(2)
                    
        except Exception as e:
            logger.error(f"Error getting OTP: {e}")
        
        if not otp_code:
            logger.warning("Failed to get fresh OTP code")
            continue
            
        used_otps.add(otp_code)
        
        # Step 4: Enter OTP
        logger.info(f"🔐 Entering OTP code: {otp_code}")
        try:
            amazon_page.bring_to_front()
            time.sleep(1)
            
            if _enter_otp_code(amazon_page, device, otp_code):
                logger.success("✓ Email verification completed!")
                if outlook_page: outlook_page.close()
                return True
            else:
                logger.warning("❌ Invalid OTP or entry failed")
                
                # Check for "Resend code" link and click it
                try:
                    resend = amazon_page.locator("a:has-text('Resend code')").first
                    if resend.is_visible(timeout=2000):
                        logger.info("🔄 Clicking 'Resend code'...")
                        device.tap(resend, "Resend Code")
                        device.tap(resend, "Resend Code")
                        logger.info("⏳ Waiting 30s for new code generation...")
                        time.sleep(30) # Increased from 5s to 30s to ensure old email isn't picked up
                        used_otps.add(otp_code) # Ensure we don't try this again
                except:
                    pass
                    
        except Exception as e:
            logger.error(f"OTP entry failed: {e}")
            
    if outlook_page: outlook_page.close()
    return False


def _is_captcha_present(page) -> bool:
    """Check if CAPTCHA is present on the page."""
    try:
        # Check URL for captcha indicators
        url = page.url.lower()
        if "captcha" in url or "/ap/challenge" in url:
            return True
        
        # Check for common CAPTCHA elements
        captcha_indicators = [
            "img[src*='captcha']",
            "#captchacharacters",
            "input[name='cvf_captcha_input']",
            "text='Enter the characters'",
            "text='Type the characters'",
            "text='Solve this puzzle'",
            "text='Choose all'",
            "button:has-text('Confirm')",
        ]
        
        for indicator in captcha_indicators:
            try:
                if page.locator(indicator).first.is_visible(timeout=500):
                    return True
            except:
                continue
                
    except Exception as e:
        logger.debug(f"CAPTCHA check error: {e}")
    
    return False


def _handle_captcha_manual(page, max_wait: int = 300) -> bool:
    """
    Prompt user to solve CAPTCHA manually and wait for completion.
    
    Args:
        page: Page with CAPTCHA
        max_wait: Maximum seconds to wait
        
    Returns:
        True if CAPTCHA solved (no longer present)
    """
    logger.warning("⚠️ CAPTCHA DETECTED - MANUAL INTERVENTION REQUIRED ⚠️")
    logger.warning("👉 Please switch to the browser and solve the CAPTCHA.")
    
    print("\n" + "=" * 60)
    print("   >>> PLEASE SOLVE CAPTCHA MANUALLY <<<")
    print("   (Will auto-detect when solved and proceed)")
    print("=" * 60 + "\n")
    
    start_time = time.time()
    poll_interval = 2
    
    while time.time() - start_time < max_wait:
        # Check if CAPTCHA is gone
        if not _is_captcha_present(page):
            logger.info("✅ CAPTCHA appears solved!")
            return True
        
        # Check if we've moved to OTP page
        if _is_otp_page(page):
            logger.info("✅ Moved to OTP page - CAPTCHA solved!")
            return True
        
        elapsed = int(time.time() - start_time)
        if elapsed % 30 == 0 and elapsed > 0:
            logger.info(f"⏳ Still waiting for CAPTCHA... ({elapsed}s)")
        
        time.sleep(poll_interval)
    
    logger.error(f"CAPTCHA timeout after {max_wait}s")
    return False


def _is_otp_page(page) -> bool:
    """Check if we're on the OTP verification page."""
    try:
        url = page.url.lower()
        if "/ap/cvf" in url or "verification" in url:
            return True
        
        # Check for OTP-specific elements
        otp_indicators = [
            "text='Enter security code'",
            "text='Verify email address'",
            "text='Enter the code'",
            "input[name='code']",
            "#cvf-input-code",
        ]
        
        for indicator in otp_indicators:
            try:
                if page.locator(indicator).first.is_visible(timeout=500):
                    return True
            except:
                continue
                
    except:
        pass
    
    return False


def _wait_for_outlook_ready(page, timeout: int = 30):
    """Wait for Outlook inbox to be ready."""
    logger.debug("Waiting for Outlook inbox to load...")
    
    start = time.time()
    while time.time() - start < timeout:
        try:
            # Check for inbox loaded indicators
            inbox_indicators = [
                "text='Inbox'",
                "div[role='option']",  # Email items
                "[data-convid]",  # Conversation items
                "button[aria-label*='New']",  # New email button
            ]
            
            for indicator in inbox_indicators:
                try:
                    if page.locator(indicator).first.is_visible(timeout=500):
                        logger.debug("Outlook inbox loaded")
                        return
                except:
                    continue
                    
        except:
            pass
        
        time.sleep(1)
    
    logger.warning("Outlook load timeout, proceeding anyway...")


def _wait_for_amazon_email(page, device, max_wait: int) -> str | None:
    """
    Wait for Amazon verification email and extract OTP code.
    
    Args:
        page: Outlook inbox page
        device: DeviceAdapter instance
        max_wait: Maximum seconds to wait
        
    Returns:
        OTP code string or None
    """
    logger.info(f"⏳ Waiting for Amazon email (max {max_wait}s)...")
    
    start_time = time.time()
    poll_interval = 5
    refresh_count = 0
    
    while time.time() - start_time < max_wait:
        # Dismiss any prompts/dialogs
        _dismiss_outlook_prompts(page, device)
        
        # Try to find and click Amazon email
        if _click_amazon_email(page, device):
            time.sleep(2)
            
            # Extract OTP from email content
            otp = _extract_otp_from_email(page)
            if otp:
                return otp
        
        # Also check if we're already viewing an email with OTP
        try:
            otp = _extract_otp_from_email(page)
            if otp:
                return otp
        except:
            pass
        
        elapsed = int(time.time() - start_time)
        if elapsed % 15 == 0 and elapsed > 0:
            logger.info(f"⏳ Still waiting for email... ({elapsed}s)")
        
        # Refresh inbox periodically
        if elapsed > 0 and elapsed % 30 == 0:
            refresh_count += 1
            if refresh_count <= 3:  # Max 3 refreshes
                try:
                    logger.info("🔄 Refreshing inbox...")
                    page.reload(wait_until="domcontentloaded")
                    time.sleep(3)
                    _wait_for_outlook_ready(page, timeout=15)
                except:
                    pass
        
        time.sleep(poll_interval)
    
    logger.error(f"Timeout: No Amazon email received in {max_wait}s")
    return None


def _dismiss_outlook_prompts(page, device):
    """Dismiss common Outlook prompts and dialogs."""
    prompts = [
        "button:has-text('Maybe later')",
        "button:has-text('Not now')",
        "button:has-text('No thanks')",
        "button:has-text('Skip')",
        "[aria-label='Close']",
    ]
    
    for selector in prompts:
        try:
            btn = page.locator(selector).first
            if btn.is_visible(timeout=300):
                device.tap(btn, "dismiss button")
                time.sleep(0.5)
        except:
            continue


def _click_amazon_email(page, device) -> bool:
    """
    Find and click Amazon verification email in Outlook.
    
    Returns:
        True if email was clicked
    """
    # Selectors for Amazon email - based on user screenshots
    amazon_selectors = [
        # By sender name
        "div:has-text('Amazon'):has-text('Verify')",
        "[aria-label*='Amazon'][aria-label*='Verify']",
        # By subject line
        "div:has-text('Verify your new Amazon account')",
        "[aria-label*='Verify your new Amazon account']",
        # Generic Amazon
        "div:has-text('Amazon.com')",
    ]
    
    for selector in amazon_selectors:
        try:
            emails = page.locator(selector).all()
            for email_el in emails[:3]:
                try:
                    if email_el.is_visible(timeout=300):
                        # Check text contains Amazon
                        text = email_el.text_content().lower()
                        if "amazon" in text and ("verify" in text or "account" in text or "otp" in text):
                            logger.info("📨 Found Amazon verification email, clicking...")
                            device.tap(email_el, "Amazon email")
                            return True
                except:
                    continue
        except:
            continue
    
    # Alternative: Find by checking all email items
    try:
        # Outlook email item selectors
        email_items = page.locator("div[role='option'], div[data-convid], [role='listitem']").all()
        
        for item in email_items[:10]:  # Check first 10 emails
            try:
                text = item.text_content().lower()
                if "amazon" in text and ("verify" in text or "account" in text):
                    logger.info("📨 Found Amazon email in list")
                    device.tap(item, "Amazon email item")
                    return True
            except:
                continue
    except:
        pass
    
    return False


def _extract_otp_from_email(page) -> str | None:
    """
    Extract OTP code from email content.
    Amazon OTP is a 6-digit number displayed prominently.
    
    Args:
        page: Page with email content visible
        
    Returns:
        OTP code string or None
    """
    try:
        # Get page content
        content = page.content()
        
        # Method 1: Look for standalone 6-digit numbers
        # Amazon OTPs are typically displayed as large text
        patterns = [
            r'>(\d{6})<',  # 6 digits between tags
            r'\s(\d{6})\s',  # 6 digits with whitespace
            r'^\s*(\d{6})\s*$',  # 6 digits on own line
            r'OTP[:\s]*(\d{6})',  # OTP: 123456
            r'code[:\s]*(\d{6})',  # code: 123456
            r'verification[:\s]*(\d{6})',  # verification: 123456
        ]
        
        for pattern in patterns:
            matches = re.findall(pattern, content, re.IGNORECASE | re.MULTILINE)
            for match in matches:
                # Validate it's a plausible OTP
                if _is_valid_otp(match):
                    logger.info(f"✅ Found OTP code: {match}")
                    return match
        
        # Method 2: Find in DOM elements - look for large displayed numbers
        try:
            # The OTP is usually in a prominent element
            number_elements = page.locator("h1, h2, h3, p, div, span, td").all()
            
            for el in number_elements:
                try:
                    text = el.text_content().strip()
                    # Check if it's just a 6-digit number
                    if text and len(text) == 6 and text.isdigit():
                        if _is_valid_otp(text):
                            logger.info(f"✅ Found OTP in element: {text}")
                            return text
                except:
                    continue
        except:
            pass
        
        # Method 3: AgentQL fallback
        try:
            import agentql
            aq_page = agentql.wrap(page)
            response = aq_page.query_elements("""
            {
                otp_code(the 6 digit verification code number, not text around it)
            }
            """)
            
            if response.otp_code:
                otp_text = response.otp_code.text_content().strip()
                if len(otp_text) == 6 and otp_text.isdigit():
                    logger.info(f"✅ Found OTP via AgentQL: {otp_text}")
                    return otp_text
        except:
            pass
            
    except Exception as e:
        logger.debug(f"OTP extraction error: {e}")
    
    return None


def _is_valid_otp(code: str) -> bool:
    """Validate that a 6-digit string is a plausible OTP."""
    if not code or len(code) != 6 or not code.isdigit():
        return False
    
    # Skip year-like numbers
    if code.startswith(('19', '20', '00')):
        return False
    
    # Skip obviously sequential or repeating
    if code in ('123456', '654321', '000000', '111111', '222222', '333333',
                '444444', '555555', '666666', '777777', '888888', '999999'):
        return False
    
    return True


def _enter_otp_code(page, device, otp_code: str) -> bool:
    """
    Enter the OTP code on Amazon verification page.
    
    Args:
        page: Amazon verification page
        device: DeviceAdapter instance
        otp_code: 6-digit OTP code
        
    Returns:
        True if successfully entered and verified
    """
    # Find OTP input field - updated selectors based on screenshot
    otp_selectors = [
        "input[name='code']",
        "#cvf-input-code",
        "input[name='cvf-input-code']",
        "input[placeholder*='code']",
        "input[placeholder*='Code']",
        "input[aria-label*='code']",
        "input[aria-label*='security']",
        "input.cvf-widget-input",
        "input[type='text'][maxlength='6']",
        "input[type='tel']",  # Sometimes numeric inputs use tel type
    ]
    
    input_found = False
    
    for selector in otp_selectors:
        try:
            input_el = page.locator(selector).first
            if input_el.is_visible(timeout=2000):
                logger.info(f"Found OTP input with selector: {selector}")
                
                # Clear and type OTP with human-like behavior
                input_el.fill("")
                time.sleep(0.3)
                
                # Use device typing for human-like behavior
                device.type_text(input_el, otp_code, "OTP code")
                time.sleep(random.uniform(0.5, 1.0))
                
                input_found = True
                break
        except:
            continue
    
    if not input_found:
        # Try AgentQL as fallback
        try:
            import agentql
            aq_page = agentql.wrap(page)
            response = aq_page.query_elements("""
            {
                security_code_input
            }
            """)
            
            if response.security_code_input:
                logger.info("Found OTP input via AgentQL")
                response.security_code_input.fill("")
                device.type_text(response.security_code_input, otp_code, "OTP code")
                time.sleep(random.uniform(0.5, 1.0))
                input_found = True
        except:
            pass
    
    if not input_found:
        logger.error("Could not find OTP input field")
        return False
    
    return _click_verify_button(page, device)

def _click_verify_button(page, device) -> bool:
    """Helper to click the verify button with caching and AgentQL verification."""
    from amazon.utils.xpath_cache import get_cached_xpath, extract_and_cache_xpath
    import agentql
    
    initial_url = page.url.lower()
    
    # Define query to check result state (Success vs Error)
    VERIFY_RESULT_QUERY = """
    {
        phone_number_input(input field for phone number, indicating success)
        otp_error_message(text saying 'invalid code', 'wrong code', 'incorrect code')
        verify_button(the verify button itself, indicating we are still on the same page)
    }
    """

    def _check_result_state():
        """Check if we succeeded or failed using AgentQL."""
        try:
            logger.info("🕵️ Using AgentQL to verify OTP submission result...")
            aq_page = agentql.wrap(page)
            response = aq_page.query_elements(VERIFY_RESULT_QUERY)
            
            if response.phone_number_input:
                logger.success("✅ AgentQL detected Phone Number input - OTP Accepted!")
                return True, True  # (Finished, Success)
            
            if response.otp_error_message:
                error_text = response.otp_error_message.text_content()
                logger.error(f"❌ AgentQL detected OTP error: {error_text}")
                return True, False # (Finished, Failed)
                
            if not response.verify_button:
                 # If verify button is gone and no error, likely moved on
                 logger.success("✅ AgentQL: Verify button gone, assuming success")
                 return True, True
                 
            return False, False # (Not Finished, still on page)
        except Exception as e:
            logger.error(f"AgentQL check failed: {e}")
            # Fallback to URL check
            if page.url.lower() != initial_url:
                return True, True
            return False, False

    # 1. Click logic (try cached, then standard, then AgentQL query)
    clicked = False
    
    # Try Cached XPath
    cached_xpath = get_cached_xpath("otp_verify_button")
    if cached_xpath:
        try:
            btn = page.locator(f"xpath={cached_xpath}").first
            if btn.is_visible(timeout=2000):
                logger.info(f"Using cached XPath for Verify: {cached_xpath}")
                device.js_click(btn, "Verify Button (Cached)")
                clicked = True
        except: pass

    # Try Standard Selectors if not clicked
    if not clicked:
        verify_selectors = [
            "#cvf-submit-otp-button", 
            "input[aria-labelledby='cvf-submit-otp-button-announce']",
            "button:has-text('Create your Amazon account')",
            "input[type='submit']"
        ]
        for selector in verify_selectors:
            try:
                btn = page.locator(selector).first
                if btn.is_visible(timeout=1000):
                    logger.info(f"Clicking standard selector: {selector}")
                    device.js_click(btn, "Verify Button")
                    clicked = True
                    break
            except: continue
            
    # Try AgentQL Click if still not clicked
    if not clicked:
        try:
            logger.info("Using AgentQL to find Verify button...")
            aq_page = agentql.wrap(page)
            response = aq_page.query_elements("{ verify_button(The 'Create your Amazon account' or 'Verify' button) }")
            if response.verify_button:
                device.js_click(response.verify_button, "Verify Button (AgentQL)")
                clicked = True
        except: pass

    if not clicked:
        logger.error("Could not find Verify button to click")
        return False
        
    # 2. Wait and Verify Result
    logger.info("⏳ Waiting for OTP submission result...")
    time.sleep(3)
    
    # retry check a few times
    for _ in range(3):
        finished, success = _check_result_state()
        if finished:
            return success
        time.sleep(2)
        
    # Final check - if we're still here, try to force click one last time?
    # Or just return False
    logger.warning("⚠️ Could not verify OTP result definitively, assuming false positive or stuck.")
    return False

