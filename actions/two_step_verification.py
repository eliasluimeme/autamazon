import time
import re
from loguru import logger
from amazon.identity_manager import Identity
from amazon.agentql_helper import query_amazon, try_cached_selectors

# 2SV Setup URL
TWO_SV_SETUP_URL = "https://www.amazon.com/a/settings/approval/setup/register?openid.mode=checkid_setup&ref_=ax_am_landing_add_2sv&openid.assoc_handle=anywhere_v2_us&openid.ns=http://specs.openid.net/auth/2.0"

def handle_login_prompt(page, identity: Identity):
    """
    Detects and handles Re-authentication/Login prompt if it appears.
    
    Sometimes Amazon asks for password again before allowing 2FA settings.
    Checks the email on screen to ensure we use the correct password.
    """
    try:
        # Check if we are on a sign-in or password prompt page
        # Indicator: /ap/signin in URL
        url = page.url.lower()
        
        # Primary check: Only proceed if URL indicates a sign-in page
        # This avoids the "Can't query n-th element" error when using locators on other pages
        if "/ap/signin" not in url:
            return False

        logger.info("🔐 Re-authentication prompt detected. Verifying identity...")

        # Determine which password to use
        password_to_use = identity.password
        
        try:
            # excessive logic to find the email on the screen to handle re-auth for a specific user
            # e.g. "Dominique Torres" or "dominique..."
            # Amazon usually shows the email/name in a div with class 'a-row' or similar, or ".a-list-item"
            
            # Simple text search for the passed identity's email
            page_content = page.content().lower()
            
            # Check if current identity email is on screen
            if identity.email.lower() in page_content:
                logger.info(f"✓ Page content matches current identity: {identity.email}")
            else:
                logger.warning(f"⚠️ Page content does NOT contain current identity email: {identity.email}")
                
                # Try to find what IS on the screen to lookup the correct password
                # This is a bit "blind" but we can try to find any email from our used list that appears on screen
                from amazon.identity_manager import find_identity_by_email
                
                # Check for cached email element first (often div.a-row or span)
                # But strict parsing is hard. Let's try to extract potential emails.
                visible_text = page.inner_text("body")
                import re
                emails = re.findall(r"[\w.+-]+@[\w-]+\.[\w.-]+", visible_text)
                
                found_correct_identity = None
                for email in emails:
                    # Filter out amazon support emails etc if needed, but our lookup is safe
                    found = find_identity_by_email(email)
                    if found:
                        found_correct_identity = found
                        break
                
                if found_correct_identity:
                    logger.info(f"✓ Found correct identity on screen: {found_correct_identity.email}")
                    password_to_use = found_correct_identity.password
                else:
                    logger.warning("Could not identify user on screen, falling back to passed identity.")

        except Exception as e:
            logger.debug(f"Identity verification logic failed: {e}")

        # 1. Try cache first
        from amazon.agentql_helper import try_cached_selectors
        cached = try_cached_selectors(page, "amazon_reauth_page")
        if cached and 'password_input' in cached:
            cached['password_input'].fill(password_to_use)
            time.sleep(0.5)
            cached['sign_in_btn'].click()
            logger.info("✓ Re-auth submitted via cache")
            return True
        
        # 2. Selectors
        password_input = page.locator("#ap_password, input[name='password']").first
        if password_input.is_visible(timeout=5000):
            password_input.fill(password_to_use)
            time.sleep(0.5)
            
            sign_in_btn = page.locator("#signInSubmit, input[type='submit'][id='signInSubmit'], input[type='submit']").first
            
            # Cache them for next time
            from amazon.agentql_helper import query_and_extract
            query_and_extract(page, "{ password_input sign_in_btn }", "amazon_reauth_page")
            
            sign_in_btn.click()
            logger.info("✓ Sign in submitted.")
            time.sleep(3)
            return True
        else:
            logger.warning("Re-auth prompt URL detected but password field not found/visible")
    except Exception as e:
        logger.warning(f"Login prompt handling failed: {e}")
    
    return False

def setup_2fa(page, identity: Identity):
    """
    Sets up 2-Step Verification for the Amazon account using 2fa.zone.
    
    Args:
        page: Playwright/AgentQL page object
        identity: Identity object to update with secret key
        
    Returns:
        bool: True if successful, False otherwise
    """
    logger.info("🔐 Starting 2-Step Verification Setup...")
    
    try:
        # 1. Navigate to 2SV Setup Page
        logger.info(f"🌐 Navigating to 2SV setup: {TWO_SV_SETUP_URL}")
        page.goto(TWO_SV_SETUP_URL, wait_until="domcontentloaded", timeout=45000)
        time.sleep(3)
        
        # 1.1 Handle potential re-authentication login prompt
        handle_login_prompt(page, identity)
        
        # 2. Select "Use an authenticator app" - XPath selectors (working format)
        auth_app_selectors = [
            "//*[@id='sia-otp-accordion-totp-header']",
            "//a[@id='sia-otp-accordion-totp-header']",
            "//span[contains(text(), 'Use an authenticator app')]",
            "//label[contains(text(), 'authenticator app')]",
            "//div[contains(text(), 'authenticator app')]",
        ]
        
        auth_selected = False
        for sel in auth_app_selectors:
            try:
                # Use xpath= prefix for XPath selectors
                if sel.startswith('//'):
                    elem = page.locator(f"xpath={sel}").first
                else:
                    elem = page.locator(sel).first
                if elem.is_visible(timeout=2000):
                    elem.click()
                    logger.info(f"✓ Selected 'Use an authenticator app' via: {sel}")
                    auth_selected = True
                    time.sleep(2)
                    break
            except Exception as e:
                logger.debug(f"Selector {sel} failed: {e}")
                continue
        
        if not auth_selected:
            logger.warning("Could not select authenticator app option, trying to continue anyway...")
        
        # 3. Extract Secret Key
        secret_key = None
        
        # CSS Selectors for the secret key area
        secret_key_selectors = [
            "#sia-totp-secret-key",
            ".totp-secret-code",
            "[data-testid='totp-secret']",
            "#sia-otp-accordion-totp-body-text",
            ".a-text-bold",
        ]
        
        # First try direct selectors
        for sel in secret_key_selectors:
            try:
                elements = page.locator(sel).all()
                for el in elements:
                    if el.is_visible(timeout=500):
                        txt = el.inner_text().strip()
                        cleaned = re.sub(r'[\s\n]', '', txt)
                        # Amazon keys are ~52 chars of Base32 (A-Z, 2-7)
                        if len(cleaned) > 40 and re.match(r'^[A-Z2-7]+$', cleaned):
                            secret_key = cleaned
                            logger.info(f"✓ Found secret key via {sel}: {secret_key[:4]}...{secret_key[-4:]}")
                            break
                if secret_key:
                    break
            except:
                continue
        
        # Fallback: Parse page text for Base32 pattern
        if not secret_key:
            try:
                # Look for instructional text
                instruction_el = page.locator("text=/type the text code below/i").first
                if instruction_el.is_visible(timeout=3000):
                    full_text = instruction_el.evaluate("el => el.parentElement?.innerText || ''")
                    
                    # Extract Base32 pattern
                    candidates = re.findall(r'[A-Z2-7\s]{30,80}', full_text)
                    for cand in candidates:
                        cleaned = re.sub(r'\s', '', cand)
                        if len(cleaned) >= 40 and re.match(r'^[A-Z2-7]+$', cleaned):
                            secret_key = cleaned
                            logger.info(f"✓ Extracted secret key from text: {secret_key[:4]}...{secret_key[-4:]}")
                            break
            except Exception as e:
                logger.debug(f"Text parsing failed: {e}")
        
        # Final fallback: Get entire page text and search
        if not secret_key:
            try:
                page_text = page.inner_text("body")
                candidates = re.findall(r'[A-Z2-7]{4,}(?:\s+[A-Z2-7]{4,})+', page_text)
                for cand in candidates:
                    cleaned = re.sub(r'\s', '', cand)
                    if len(cleaned) >= 40 and len(cleaned) <= 80:
                        secret_key = cleaned
                        logger.info(f"✓ Found secret key in page: {secret_key[:4]}...{secret_key[-4:]}")
                        break
            except:
                pass
        
        if not secret_key:
            logger.error("❌ Could not find secret key on the page")
            return False
            
        # 4. Save Secret Key
        # Save to identity object (we need to potentially persist this to file later)
        # For now, we just attach it to the instance
        identity.two_fa_secret = secret_key
        # TODO: Persist to file if needed immediately, or let main loop handle it
        
        # 5. Get OTP from 2fa.zone
        logger.info("🔑 Generating OTP via 2fa.zone...")
        otp_code = _get_otp_from_2fa_zone(page.context, secret_key)
        
        if not otp_code:
            logger.error("❌ Failed to generate OTP")
            return False
            
        logger.info(f"✓ Generated OTP: {otp_code}")
        
        # 6. Verify OTP on Amazon
        # Input: //*[@id="ch-auth-app-code-input"] or input[name='verifyCode']
        try:
            # Using user provided xpath or probable ID
            otp_input = page.locator("//*[@id='ch-auth-app-code-input']").first
            if not otp_input.is_visible():
                otp_input = page.locator("input[name='verificationCode'], input#verificationCode").first
            
            otp_input.fill(otp_code)
            time.sleep(0.5)
            
            # Click Verify: "Verify OTP and continue" using user-provided selector
            verify_btn_selectors = [
                # User-provided XPath
                "xpath=//*[@id='ch-auth-app-submit-button']/span",
                "xpath=//*[@id='ch-auth-app-submit-button']",
                # Fallback selectors
                "#ch-auth-app-submit-button",
                "button:has-text('Verify OTP and continue')",
                "input[type='submit']",
                ".a-button-input",
            ]
            
            for sel in verify_btn_selectors:
                try:
                    verify_btn = page.locator(sel).first
                    if verify_btn.is_visible(timeout=2000):
                        verify_btn.click(force=True)
                        logger.info("✓ Clicked 'Verify OTP and continue' button")
                        break
                except:
                    continue
            
            logger.info("✓ Submitted OTP")
            time.sleep(5)
            
            # 7. Check Success
            # Should redirect to a success page or Settings
            if "enable-success" in page.url or "success" in page.url or page.locator("text=Success").is_visible():
                logger.success("🎉 2-Step Verification Enabled Successfully!")
                # Check for post-verification steps
                handle_post_2fa_verification(page, identity)
                return True
            else:
                # Check for errors
                if page.locator(".a-alert-error").is_visible():
                    logger.error("❌ Amazon verification failed (Invalid OTP?)")
                    return False
                
                # Assume success if we moved away from setup page
                logger.success("✓ 2-Step Verification setup flow completed (assumed success)")
                # Check for post-verification steps
                handle_post_2fa_verification(page, identity)
                return True
                
        except Exception as e:
            logger.error(f"Error during verification step: {e}")
            return False

    except Exception as e:
        logger.error(f"2FA Setup Failed: {e}")
        return False

def _get_otp_from_2fa_zone(context, secret):
    """
    Opens a new tab to 2fa.zone and retrieves OTP.
    """
    page_2fa = None
    try:
        page_2fa = context.new_page()
        page_2fa.goto("https://2fa.zone", wait_until="domcontentloaded")
        
        # User XPaths:
        # Input: //*[@id="secret-input-js"]
        # Button: //*[@id="btn-js"]
        # Code: //*[@id="code_js"]
        
        # 1. Enter Secret
        page_2fa.locator("//*[@id='secret-input-js']").fill(secret)
        time.sleep(0.5)
        
        # 2. Click Generation Button
        # Use force=True to avoid strict visibility checks if overlay/scrolling is an issue
        gen_btn = page_2fa.locator("//*[@id='btn-js']")
        
        try:
            # wait for button first
            if gen_btn.is_visible(timeout=5000):
                # We use a short timeout for the click itself. 
                # If it times out, we assume the action might have still triggered or the page is just slow to respond,
                # but we proceed to check for the code anyway as requested.
                gen_btn.click(force=True, timeout=2000)
            else:
                 # Fallback JS click if standard one isn't visible
                 logger.debug("Button not visible standardly, using JS click")
                 page_2fa.evaluate("document.getElementById('btn-js').click()")
        except Exception as e:
            # We catch ALL exceptions here (including TimeoutError) and proceed
            logger.warning(f"Click action raised error (likely timeout), but proceeding to check for code: {str(e)}")
            # Attempt JS click as backup if the main click failed/timed out
            try:
                page_2fa.evaluate("document.getElementById('btn-js').click()")
            except:
                pass
            
        time.sleep(1.0)
        
        # 3. Get Code
        # Wait for code to appear (it might take a second)
        code_el = page_2fa.locator("//*[@id='code_js']")
        
        # Wait up to 5s for the text to change/appear
        for _ in range(10):
            code = code_el.text_content().strip()
            # Clean up code (sometimes it has spaces or formatting)
            otp = "".join(filter(str.isdigit, code))
            
            if otp and len(otp) >= 6:
                 logger.info(f"✓ Retrieved OTP from 2fa.zone: {otp}")
                 return otp
            time.sleep(0.5)
        
        logger.warning("Timeout waiting for OTP code to appear")
        return None
        
    except Exception as e:
        logger.error(f"2fa.zone error: {e}")
        return None
    finally:
        if page_2fa:
            page_2fa.close()

def handle_post_2fa_verification(page, identity: Identity):
    """
    Handles potential steps that appear after 2FA setup:
    1. Enter verification code (sent to email) - similar to signup flow
    2. Sign-in prompt (enter password)
    3. Passkey setup (skip it)
    """
    logger.info("🔍 Checking for post-2FA verification steps...")
    
    start_time = time.time()
    seen_emails = set()
    while time.time() - start_time < 60: # Check for 60 seconds to allow email arrival
        url = page.url
        found_action = False
        
        # --- 1. Email Verification Code Step ---
        # Detect by URL or by visible input fields (multiple possible selectors)
        otp_input_visible = False
        otp_input_selectors = [
            "input[name='code']",
            "#input-box-otp",
            "#cvf-input-code",
            "input[name='otpCode']",
            "input.cvf-widget-input",
        ]
        for sel in otp_input_selectors:
            try:
                if page.locator(sel).first.is_visible(timeout=300):
                    otp_input_visible = True
                    break
            except:
                continue
        
        if "/ap/cvf/transactionapproval" in url or otp_input_visible:
            logger.info("📧 Email verification code prompt detected!")
            found_action = True
            try:
                # Open Outlook to get code
                context = page.context
                outlook_page = context.new_page()
                
                logger.info("Opening Outlook to retrieve code...")
                outlook_page.goto("https://outlook.live.com/mail/0/inbox", wait_until="domcontentloaded")
                time.sleep(3)
                
                # Wait for email list and get code
                email_code = None
                
                try:
                    # 0. Dismiss "Work offline" / App Install modal
                    try:
                        logger.info("Checking for Outlook app/offline modal...")
                        modal_close_btn = outlook_page.locator("button:has-text('No, thanks'), [aria-label='Close'], button:has-text('Later')").first
                        if modal_close_btn.is_visible(timeout=5000):
                            logger.info("📱 'Work offline' app modal detected - Dismissing...")
                            modal_close_btn.click()
                            time.sleep(2)
                    except Exception as e:
                        logger.debug(f"Modal check warning: {e}")

                    # 1. Wait for email list to load - articles are the email items
                    try:
                        outlook_page.wait_for_selector("article[data-testid='MailListItem'], div[role='option']", timeout=15000)
                    except:
                        logger.warning("Timeout waiting for Outlook email list to load")
                    
                    time.sleep(1)  # Brief stabilization
                    
                    # 2. Find the FIRST (latest) Amazon email
                    target_email = None
                    seen_key = None
                    
                    # 1st Priority: Exact match using aria-label (more robust)
                    # We look specifically for "Account data access attempt" first
                    try:
                        aria_selectors = [
                            "[aria-label*='amazon.com'][aria-label*='Account data access attempt']",
                            "[aria-label*='amazon.com'][aria-label*='Account data access']",
                        ]
                        for sel in aria_selectors:
                            elements = outlook_page.locator(sel).all()
                            for el in elements:
                                aria_val = el.get_attribute("aria-label") or ""
                                # Clean up the value to check for fresh indicators if possible
                                # Outlook labels often include "just now" or "X minutes ago"
                                lower_aria = aria_val.lower()
                                if "amazon" in lower_aria and aria_val not in seen_emails:
                                    # Very basic check for freshness: avoid emails that mention "yesterday" or days of week if possible
                                    # although this is brittle across locales
                                    target_email = el
                                    seen_key = aria_val
                                    logger.info(f"📨 Found primary Amazon email via aria-label: {sel}")
                                    break
                            if target_email:
                                break
                    except Exception as e:
                        logger.debug(f"Aria priority check: {e}")

                    if not target_email:
                        # 2nd Priority: Look for general email items and check their text
                        email_items = outlook_page.locator("article[data-testid='MailListItem']").all()
                        if not email_items:
                            email_items = outlook_page.locator("div[role='group'] article, div[role='option']").all()
                        
                        logger.info(f"Found {len(email_items)} emails, searching for 'Account data access attempt'...")
                        
                        # Search for the TARGET email specifically first
                        for item in email_items[:10]:
                            try:
                                text = item.text_content().lower()
                                if "amazon.com" in text and "account data access attempt" in text:
                                    preview = text[:150].replace('\n', ' ')
                                    if preview not in seen_emails:
                                        target_email = item
                                        seen_key = preview
                                        logger.info(f"📨 Found target Amazon email in text: {preview[:100]}...")
                                        break
                            except:
                                continue

                        # 3rd Priority: ONLY IF we've been waiting for a while, consider fallback amazon emails
                        # This prevents us from grabbing a stale "Developer Account" email while the real one is still being delivered
                        if not target_email and (time.time() - start_time > 20):
                            logger.info("Target email not found after 20s, checking for fallback Amazon emails...")
                            for item in email_items[:5]:
                                try:
                                    text = item.text_content().lower()
                                    if "amazon" in text and ("verification" in text or "verify" in text or "otp" in text or "code" in text):
                                        # Avoid the "atamazon appstore team" specifically if it's clearly not what we want
                                        if "appstore" in text and "developer" in text:
                                            continue
                                            
                                        preview = text[:150].replace('\n', ' ')
                                        if preview not in seen_emails:
                                            target_email = item
                                            seen_key = preview
                                            logger.info(f"📨 Found fallback Amazon email: {preview[:100]}...")
                                            break
                                except:
                                    continue

                    if target_email:
                        if seen_key:
                            seen_emails.add(seen_key)
                        logger.info("✓ Found Amazon email in list, clicking...")
                        
                        # Record current URL to detect navigation
                        pre_click_url = outlook_page.url
                        
                        # Click the email item
                        try:
                            target_email.click(force=True, timeout=5000)
                        except Exception as click_err:
                            logger.warning(f"Standard click failed, trying JS: {click_err}")
                            try:
                                target_email.evaluate("el => el.click()")
                            except:
                                # Last resort: dispatch click event
                                target_email.dispatch_event("click")
                        
                        # Wait for email to open - Outlook navigates to /inbox/id/...
                        for _ in range(10):
                            time.sleep(1)
                            current_url = outlook_page.url
                            if current_url != pre_click_url and "/id/" in current_url:
                                logger.info("✓ Email opened (URL changed)")
                                break
                        else:
                            # URL didn't change, but content might have loaded in reading pane
                            time.sleep(2)
                        
                        # 3. Extract OTP code from the opened email
                        # Fast path: look for 6-digit code directly in the email body
                        # The OTP span is inside div.x_body in nested tables
                        try:
                            # Direct span extraction from email body
                            code_spans = outlook_page.locator("div.x_body span, div[class*='body'] span").all()
                            for span in code_spans:
                                try:
                                    txt = span.text_content().strip()
                                    if len(txt) == 6 and txt.isdigit() and not txt.startswith(('19', '20', '00')):
                                        email_code = txt
                                        logger.success(f"✓ Found OTP code directly from span: {email_code}")
                                        break
                                except:
                                    continue
                        except:
                            pass
                        
                        # If fast path didn't work, try reading pane content
                        if not email_code:
                            content_selectors = [
                                "div.x_body",                    # Outlook email body
                                "#ReadingPaneContainerId",
                                "[aria-label='Message body']",
                                "div[role='main']",
                                ".wide-content-host",
                            ]
                            
                            content_el = None
                            for sel in content_selectors:
                                try:
                                    el = outlook_page.locator(sel).first
                                    if el.is_visible(timeout=1500):
                                        content_el = el
                                        logger.debug(f"Found email content via: {sel}")
                                        break
                                except:
                                    continue
                            
                            # Fallback to body
                            if not content_el:
                                content_el = outlook_page.locator("body")
                            
                            # Read content multiple times as it loads
                            for attempt in range(6):
                                try:
                                    content = content_el.text_content() or ""
                                    # Look for "verification code is: XXXXXX" pattern
                                    code_match = re.search(r'verification code\s*(?:is)?[:\s]*(\d{6})', content, re.IGNORECASE)
                                    if code_match:
                                        email_code = code_match.group(1)
                                        logger.success(f"✓ Found verification code: {email_code}")
                                        break
                                    
                                    # Fallback: any standalone 6-digit number
                                    match = re.search(r'\b(\d{6})\b', content)
                                    if match:
                                        candidate = match.group(1)
                                        if not candidate.startswith(('19', '20', '00')):
                                            email_code = candidate
                                            logger.success(f"✓ Found code in email: {email_code}")
                                            break
                                except:
                                    pass
                                time.sleep(1)
                        
                        if not email_code:
                            # Last resort: inner_text for cleaner extraction
                            try:
                                body_text = outlook_page.inner_text("body")
                                code_match = re.search(r'verification code\s*(?:is)?[:\s]*(\d{6})', body_text, re.IGNORECASE)
                                if code_match:
                                    email_code = code_match.group(1)
                                    logger.success(f"✓ Found code via inner_text: {email_code}")
                                else:
                                    match = re.search(r'\b(\d{6})\b', body_text)
                                    if match and not match.group(1).startswith(('19', '20', '00')):
                                        email_code = match.group(1)
                                        logger.success(f"✓ Found code in page body: {email_code}")
                            except:
                                pass
                    else:
                        logger.warning("Amazon email not found in Outlook inbox")

                    if not email_code:
                         logger.warning("Checked for Amazon email but no 6-digit code found.")
                         
                except Exception as e:
                   logger.error(f"Error retrieving email: {e}")
                
                outlook_page.close()
                page.bring_to_front()
                
                if email_code:
                    # Enter code on Amazon transaction approval page
                    code_entered = False
                    code_input_selectors = [
                        "input[name='code']",
                        "#input-box-otp",
                        "#cvf-input-code",
                        "input[name='otpCode']",
                        "input.cvf-widget-input",
                        "input[type='text'][maxlength='6']",
                        "input[type='tel']",
                    ]
                    
                    for sel in code_input_selectors:
                        try:
                            inp = page.locator(sel).first
                            if inp.is_visible(timeout=2000):
                                inp.fill(email_code)
                                code_entered = True
                                logger.info(f"✓ Entered code via: {sel}")
                                break
                        except:
                            continue
                    
                    if not code_entered:
                        logger.error("❌ Could not find OTP input field on Amazon page")
                        continue
                    
                    time.sleep(0.5)
                    
                    # Click submit button
                    submit_selectors = [
                        "input[type='submit']",
                        "button[type='submit']",
                        "#cvf-submit-otp-button",
                        "button:has-text('Submit code')",
                        "button:has-text('Verify')",
                        ".a-button-input",
                    ]
                    
                    for sel in submit_selectors:
                        try:
                            btn = page.locator(sel).first
                            if btn.is_visible(timeout=2000):
                                btn.click(force=True)
                                logger.success(f"✓ Submitted verification code via: {sel}")
                                break
                        except:
                            continue
                    
                    time.sleep(3)
                    continue 
                else:
                    logger.error("❌ Could not retrieve code from Outlook")
                    time.sleep(5) # Wait before retry loop to not spam Outlook
            except Exception as e:
                logger.error(f"Error handling email verification: {e}")

        # --- 2. Sign-in Prompt ---
        if "/ap/signin" in url or page.locator("#ap_password").is_visible(timeout=500):
            logger.info("🔐 Sign-in prompt detected")
            found_action = True
            try:
                pwd_input = page.locator("#ap_password").first
                if pwd_input.is_visible():
                    pwd_input.fill(identity.password)
                    time.sleep(0.5)
                    
                    # Click sign in
                    page.locator("#signInSubmit, input[type='submit']").first.click()
                    logger.success("✓ Signed in with password")
                    time.sleep(3)
                    continue
            except Exception as e:
                logger.error(f"Error handling sign-in: {e}")

        # --- 3. Passkey Skip ---
        # "Hmm, something went wrong" often appears on passkey page with "Skip setup"
        is_passkey_page = "/webauthn/nudge" in url or \
                          page.locator("text='Skip the password next time'").is_visible(timeout=500) or \
                          page.locator("text='Skip setup'").is_visible(timeout=500)

        if is_passkey_page:
            logger.info("🔑 Passkey prompt detected - Skipping...")
            found_action = True
            
            # Reset timer to allow for subsequent steps
            start_time = time.time()
            
            from amazon.actions.passkey import handle_passkey_nudge
            # Force retry loop for handle_passkey_nudge if needed
            if handle_passkey_nudge(page):
                logger.success("✓ Skipped passkey setup")
                time.sleep(2)
                continue

        # --- 4. 'Almost done' / Turn on 2SV Page ---
        # User requested AgentQL for detection
        if "/approval/setup/howto" in url:
            logger.info("🏁 'Almost done' page detected. Checking for 'Turn on' button...")
            found_action = True
            start_time = time.time() # Reset timer
            
            try:
                import agentql
                # Use AgentQL to verify we are on the right page and find the button if needed
                aq_page = agentql.wrap(page)
                try:
                    response = aq_page.query_elements("""
                    {
                        turn_on_button(the 'Got it. Turn on Two-Step Verification' button)
                    }
                    """)
                    if response.turn_on_button:
                        logger.info("✅ AgentQL detected 'Turn on' button")
                except:
                    pass

                # Click using provided selectors (Reliable)
                turn_on_selectors = [
                    "#enable-mfa-form-submit",
                    "xpath=//*[@id='enable-mfa-form-submit']",
                    "button:has-text('Turn on Two-Step Verification')",
                    "input[type='submit']"
                ]
                
                clicked = False
                for sel in turn_on_selectors:
                    try:
                        btn = page.locator(sel).first
                        if btn.is_visible(timeout=2000):
                            btn.click()
                            logger.success(f"✓ Clicked 'Turn on Two-Step Verification' via: {sel}")
                            clicked = True
                            break
                    except:
                        continue
                
                if not clicked:
                    # Fallback to AgentQL click
                    if response and response.turn_on_button:
                         logger.info("Using AgentQL button for click...")
                         response.turn_on_button.click()
                         clicked = True
                         
                if clicked:
                    time.sleep(3)
                    continue
            except Exception as e:
                logger.error(f"Error handling 'Almost done' page: {e}")

        # --- 5. Payment selection page (Success) ---
        if "/dppui/pay-select" in url or page.locator("text='How would you like to pay?'").is_visible(timeout=500):
            logger.success("🎉 Payment selection page detected! Sign-up successful.")
            # Explicitly do NOT click "Place your order" as per user request
            found_action = True
            break
        
        if found_action:
             # Reset timer if we did something, so we don't timeout prematurely on the next step
             start_time = time.time()
             continue

        # If nothing found, wait a bit and check again
        time.sleep(2)
        # If URL stabilized and isn't one of the known ones, maybe we are done
        # But give it enough time (don't break too early)
            
    logger.info("✓ Post-verification checks completed")
