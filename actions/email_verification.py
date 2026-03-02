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
from amazon.utils.imap_helper import get_otp_from_imap
from amazon.core.interaction import InteractionEngine


def _safe_is_visible(locator, timeout=500):
    """Safely check if an element is visible without throwing exceptions."""
    try:
        return locator.is_visible(timeout=timeout)
    except:
        return False


def handle_email_verification(browser_context, amazon_page, device, email: str, max_wait: int = 120, purpose: str = "signup", used_otps: set = None) -> bool:
    """
    Handle the complete email verification flow.
    
    Args:
        browser_context: Playwright browser context
        amazon_page: The Amazon page waiting for OTP
        device: DeviceAdapter instance
        email: Email address to check
        max_wait: Maximum seconds to wait for email
        purpose: "signup" or "reauth" - determines button labels and logic
        used_otps: Optional set of already used OTP codes to skip
    """
    logger.info(f"📧 Starting email verification flow (Purpose: {purpose})...")
    
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
    
    # Step 0.5: Try IMAP fast retrieval first
    # We need the email password. Identity is not passed here, so we might need to find it.
    # For now, we assume the identity manager or session state might provide it.
    # If we don't have password, we skip to browser-based Outlook.
    # from amazon.identity_manager import find_identity_by_email
    # ident = find_identity_by_email(email)
    
    # if ident and ident.password:
    #     otp_code = get_otp_from_imap(ident.email, ident.password, timeout=60)
    #     if otp_code:
    #         logger.success(f"✅ OTP retrieved via IMAP: {otp_code}")
    #         amazon_page.bring_to_front()
    #         if _enter_otp_code(amazon_page, device, otp_code, purpose):
    #             logger.success(f"✓ Email verification completed via IMAP! ({purpose})")
    #             return True
    
    # logger.info("IMAP retrieval failed or unavailable, falling back to browser-based Outlook...")
    
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
    if used_otps is None:
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
            # ALWAYS go to inbox at start of wait to ensure we don't see old cached list or old email
            try:
                logger.info("📬 Re-navigating to Outlook inbox for fresh list...")
                outlook_page.goto("https://outlook.live.com/mail/0/inbox", wait_until="domcontentloaded", timeout=30000)
                _wait_for_outlook_ready(outlook_page)
                time.sleep(3)
            except: pass
            
            # loop to ensure we get a NEW code
            otp_wait_start = time.time()
            page_refreshed = False
            while time.time() - otp_wait_start < (max_wait if attempt == 0 else 60):
                otp_code = _wait_for_amazon_email(outlook_page, device, 10, used_otps=used_otps) # short poll
                if otp_code and otp_code not in used_otps:
                    break
                elif otp_code in used_otps:
                    logger.info(f"Code {otp_code} was already used. Waiting for a fresh email...")
                    if not page_refreshed and (time.time() - otp_wait_start) > 15:
                         try:
                            logger.info("🔄 Refreshing Outlook to look for new messages...")
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
            
            if _enter_otp_code(amazon_page, device, otp_code, purpose):
                logger.success(f"✓ Email verification completed! ({purpose})")
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
                        logger.info("⏳ Waiting 10s for new code generation...")
                        time.sleep(10) # Increased from 5s to 10s to ensure old email isn't picked up
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
            "text='Enter verification code'",
            "input[name='code']",
            "#cvf-input-code",
            "input[name='cvf_captcha_input']"
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


def _wait_for_amazon_email(page, device, max_wait: int, used_otps: set = None) -> str | None:
    """
    Wait for Amazon verification email and extract OTP code.
    
    Args:
        page: Outlook inbox page
        device: DeviceAdapter instance
        max_wait: Maximum seconds to wait
        used_otps: Set of already-used OTP codes to skip
        
    Returns:
        OTP code string or None
    """
    logger.info(f"⏳ Waiting for Amazon email (max {max_wait}s)...")
    if used_otps is None:
        used_otps = set()
    
    start_time = time.time()
    poll_interval = 5
    refresh_count = 0
    
    while time.time() - start_time < max_wait:
        # Dismiss any prompts/dialogs
        _dismiss_outlook_prompts(page, device)
        
        # NOTE: Do NOT extract OTP from whatever is currently on screen here.
        # The reading pane may still show a previously opened (stale) email.
        # Always navigate into a fresh email click before extracting.
        
        # Try to find and click Amazon email (now verifies email actually opened)
        if _click_amazon_email(page, device, used_otps=used_otps):
            # Email was clicked AND verified opened — try OTP extraction
            # Try multiple times since email content may still be rendering
            for extract_attempt in range(3):
                time.sleep(1.5)
                otp = _extract_otp_from_email(page)
                if otp and otp not in used_otps:
                    return otp
                elif otp in used_otps:
                    logger.warning(f"  ⚠️ Email opened but OTP {otp} was already used, skipping...")
                    break  # Don't keep re-extracting from the same old email
                logger.debug(f"  OTP extraction attempt {extract_attempt + 1}/3 — no code found yet")
            
            # If we got here, email opened but no OTP found
            logger.warning("Email opened but couldn't extract OTP. Navigating back to inbox...")
            try:
                page.goto("https://outlook.live.com/mail/0/inbox", wait_until="domcontentloaded", timeout=15000)
                _wait_for_outlook_ready(page, timeout=10)
                time.sleep(1)
            except:
                pass
        else:
            logger.debug("Amazon email not found or couldn't be opened in this cycle")
        
        elapsed = int(time.time() - start_time)
        if elapsed % 15 == 0 and elapsed > 0:
            logger.info(f"⏳ Still waiting for email... ({elapsed}s)")
        
        # Refresh inbox periodically
        if elapsed > 0 and elapsed % 30 == 0:
            refresh_count += 1
            if refresh_count <= 3:  # Max 3 refreshes
                try:
                    logger.info("🔄 Refreshing inbox...")
                    page.goto("https://outlook.live.com/mail/0/inbox", wait_until="domcontentloaded", timeout=15000)
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
        "text='Maybe later'",
        "text='Not now'",
        "text='No thanks'",
        "button:has-text('Maybe later')",
        "span:has-text('Maybe later')",
        "button:has-text('Not now')",
        "button:has-text('No thanks')",
        "button:has-text('Skip')",
        "button:has-text('Add to home')",
        "[aria-label='Close']",
        "i[data-icon-name='Cancel']",
    ]
    
    for selector in prompts:
        try:
            btn = page.locator(selector).first
            if _safe_is_visible(btn, timeout=100):
                logger.debug(f"Dismissing Outlook prompt: {selector}")
                device.tap(btn, "dismiss button")
                time.sleep(1)
        except:
            continue

def _verify_email_opened(page, timeout: int = 3) -> bool:
    """
    Verify that an email was actually opened (not just clicked on a container).
    Checks for email body indicators or URL change to /mail/0/id/.
    """
    start = time.time()
    while time.time() - start < timeout:
        try:
            url = page.url
            # Outlook changes URL to include message ID when email is opened
            if "/mail/0/id/" in url or "/mail/id/" in url:
                logger.debug("  ✅ Email opened (URL contains message ID)")
                return True
            
            # Check for email body / reading pane indicators
            body_indicators = [
                "div[role='document']",           # Email body container
                "div[aria-label='Message body']",  # Message body
                "div.wide-content-host",           # Wide content host (email view)
                "div[data-testid='ReadingPane']",  # Reading pane
                "button[aria-label='Reply']",      # Reply button = email is open
                "button[aria-label='Reply all']",  
                "button[aria-label='Delete']",     # Delete visible = email view
            ]
            for indicator in body_indicators:
                try:
                    if page.locator(indicator).first.is_visible(timeout=200):
                        logger.debug(f"  ✅ Email opened (found '{indicator}')")
                        return True
                except:
                    continue
        except:
            pass
        time.sleep(0.5)
    
    logger.debug("  ❌ Email did NOT open after click (no body indicators found)")
    return False


def _click_amazon_email(page, device, used_otps: set = None) -> bool:
    """
    Find and click Amazon verification email in Outlook.
    Prioritizes the FIRST (most recent) Amazon email in the inbox to avoid
    re-opening a stale email that produced an already-used OTP.
    
    Returns:
        True if email was clicked AND actually opened (verified).
    """
    if used_otps is None:
        used_otps = set()
    # Helper to attempt click and verify email opened
    def _try_click_and_verify(el, label: str) -> bool:
        """Click an email element and verify it actually opened."""
        try:
            el.scroll_into_view_if_needed()
            time.sleep(0.3)
        except:
            pass
        
        # Always prefer js_click for reliability on mobile
        try:
            device.js_click(el, label)
        except:
            try:
                device.tap(el, label)
            except:
                return False
        
        time.sleep(1)
        return _verify_email_opened(page, timeout=3)
    
    # 0. User Requested & Semantic Selectors - High Priority
    selectors = [
        "article[data-testid='MailListItem']", # DevTools semantic - High Priority
        "xpath=//*[@id='screen-stack-root']/div/div/main/div/div/div[2]", # User requested
        "div[role='option']", # Standard Outlook
    ]
    
    for selector in selectors:
        try:
            # Check all matching elements — find FIRST (most recent) one with "amazon" text
            items = page.locator(selector).all()
            for email_el in items[:5]:  # Check top 5, first = most recent
                if not _safe_is_visible(email_el, timeout=200):
                    continue
                text = email_el.text_content().lower()
                if "amazon" in text:
                    # Quick pre-check: if this element's visible text contains an already-used OTP, skip it
                    if used_otps and any(otp in text for otp in used_otps):
                        logger.info(f"  ⏩ Skipping email (contains already-used OTP): {text[:80]}")
                        continue
                    logger.info(f"📨 Found Amazon email via '{selector}', clicking (first match = most recent)...")
                    if _try_click_and_verify(email_el, "Amazon email (semantic)"):
                        return True
                    else:
                        logger.warning(f"  ⚠️ Click on '{selector}' didn't open email, trying next...")
        except: continue

    # 1. Look for VERY RECENT Amazon emails (e.g. 'now', '0 min', '1 min')
    recent_selectors = [
        "div:has-text('Account data access attempt'):has-text('now')",
        "div:has-text('Account data access attempt'):has-text('min')",
        "div:has-text('Your Amazon security code'):has-text('now')",
        "div:has-text('Your Amazon security code'):has-text('min')",
        "div:has-text('Verify your new Amazon account'):has-text('now')",
        "div:has-text('Amazon security alert'):has-text('now')",
        "div:has-text('Amazon security alert'):has-text('min')",
    ]
    
    for selector in recent_selectors:
        try:
            # Use last() instead of first() — innermost match is more specific
            email_el = page.locator(selector).last
            if _safe_is_visible(email_el, timeout=200):
                logger.info(f"✨ Found RECENT Amazon email: {selector}")
                if _try_click_and_verify(email_el, "Recent Amazon email"):
                    return True
                logger.warning(f"  ⚠️ Recent email click didn't open, trying next...")
        except: continue

    # 2. Fallback to Amazon email using tighter scoped selectors
    amazon_subject_keywords = [
        'Account data access attempt',
        'Your Amazon security code',
        'Amazon security alert',
        'Verify your new Amazon account',
        'Amazon password assistance',
        'One Time Password',
        'security code',
    ]
    
    # Try role='option' items first (Outlook email list items)
    try:
        list_items = page.locator("div[role='option']").all()
        for item in list_items[:5]:
            try:
                text = item.text_content().lower()
                if "amazon" in text:
                    if used_otps and any(otp in text for otp in used_otps):
                        logger.info(f"  ⏩ Skipping list item (stale OTP found in preview): {text[:80]}")
                        continue
                    logger.info(f"📨 Found Amazon email in role='option' list item")
                    if _try_click_and_verify(item, "Amazon email (list item)"):
                        return True
                    logger.warning("  ⚠️ List item click didn't open, trying next...")
            except:
                continue
    except:
        pass
    
    # Try data-convid items (another Outlook email attribute)
    try:
        conv_items = page.locator("div[data-convid]").all()
        for item in conv_items[:5]:
            try:
                text = item.text_content().lower()
                if "amazon" in text:
                    if used_otps and any(otp in text for otp in used_otps):
                        logger.info(f"  ⏩ Skipping conv item (stale OTP found in preview): {text[:80]}")
                        continue
                    logger.info(f"📨 Found Amazon email via data-convid")
                    if _try_click_and_verify(item, "Amazon email (conversation)"):
                        return True
                    logger.warning("  ⚠️ Conversation item click didn't open, trying next...")
            except:
                continue
    except:
        pass
    
    # 3. Last resort: broad subject-line text selectors with .last (innermost match)
    for keyword in amazon_subject_keywords:
        try:
            selector = f"div:has-text('{keyword}')"
            email_el = page.locator(selector).last  # .last = innermost, most specific
            if _safe_is_visible(email_el, timeout=200):
                logger.info(f"📨 Found Amazon email via '{selector}' (last/innermost)")
                if _try_click_and_verify(email_el, "Amazon email (text match)"):
                    return True
                logger.warning(f"  ⚠️ Text-match click didn't open, trying next...")
        except:
            continue
    
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


def _enter_otp_code(page, device, otp_code: str, purpose: str = "signup") -> bool:
    """
    Enter the OTP code on Amazon verification page.
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
    
    return _click_verify_button(page, device, purpose)

def _click_verify_button(page, device, purpose: str = "signup") -> bool:
    """Helper to click the verify button with robust transition check."""
    interaction = InteractionEngine(page, device)
    initial_url = page.url
    
    # Purpose-based configuration
    if purpose == "reauth":
        description = "Submit Code Button"
        query = "{ submit_code_button(the primary button to verify the security code) }"
    else:
        description = "Create Amazon Account Button"
        query = "{ create_amazon_account_button(the primary button to submit the OTP and create the account) }"
    
    # Use biomechanical=True for the final submission button
    success = interaction.smart_click(
        description=description,
        selectors=[
            "xpath=//*[@id='cvf-submit-otp-button']/span/input", 
            "xpath=//*[@id='cvf-submit-otp-button-announce']", 
            "#cvf-submit-otp-button-announce",
            "button:has-text('Submit code')",
            "input[aria-label='Verify OTP Button']",
            "button:has-text('Create your Amazon account')",
            "span:has-text('Create your Amazon account')",
            "#cvf-submit-otp-button", 
            "input[name='cvf_submit_otp_button']",
            "button:has-text('Verify')",
            "input[type='submit'][value='Verify']",
            "span.a-button-inner:has-text('Verify')",
            "input[type='submit']"
        ],
        agentql_query=query,
        cache_key="cvf_verify_button",
        biomechanical=True 
    )
    
    if not success:
        logger.error("❌ Could not click Verify button via any method.")
        return False
        
    # Wait and verify REAL progression (don't be optimistic)
    logger.info("⏳ Monitoring for page transition after Verify click...")
    
    # Check for up to 10 seconds with high resolution (0.5s chunks)
    for _ in range(20):
        current_url = page.url.lower()
        
        # 1. Success indicator: URL changed away from CVF
        if "/ap/cvf" not in current_url and "verification" not in current_url:
            logger.success("✅ Page transitioned - Success!")
            return True
            
        # 2. Check for errors visible on page
        error_selectors = [
            ".a-alert-error",
            "#cvf-error-message",
            "text='invalid code'",
            "text='wrong code'",
            "text='incorrect code'",
            "text='Please enter the OTP'"
        ]
        for sel in error_selectors:
            try:
                if page.locator(sel).first.is_visible(timeout=50):
                    error_text = page.locator(sel).first.text_content().strip()
                    logger.error(f"❌ OTP submission failed error: {error_text}")
                    return False
            except: continue
        
        time.sleep(0.5)
            
    # If we are still here, it probably didn't work
    if page.url == initial_url:
        logger.warning("⚠️ Still on CVF page after 10s. Click might have failed silently.")
        return False
        
    return True


