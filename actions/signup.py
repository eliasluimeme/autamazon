"""
Account Creation Actions for Amazon Automation

Handles the signup/registration flow:
- Selecting "Create account" option
- Filling registration form
- Handling verification steps
"""

import time
import random
from loguru import logger

from amazon.config import DELAYS
from amazon.element_locator import ElementLocator
from amazon.device_adapter import DeviceAdapter


def handle_new_customer_intent(page, device: DeviceAdapter = None) -> bool:
    """
    Handle the 'Looks like you're new to Amazon' page.
    Clicks 'Proceed to create an account'.
    """
    if device is None:
        device = DeviceAdapter(page)
        
    logger.info("Handling 'New to Amazon' intent page...")
    
    initial_url = page.url

    # 1. Try cache or AgentQL via query_amazon
    from amazon.agentql_helper import query_amazon
    try:
        results = query_amazon(page, "intent_page", cache=True)
        
        if 'proceed_button' in results and results['proceed_button']['element']:
            btn = results['proceed_button']['element']
            logger.info("Found intent button via AgentQL")
            device.scroll_to_element(btn, "Proceed Button")
            
            # Try JS click first
            device.js_click(btn, "Proceed Button (AgentQL)")
            time.sleep(2)
            
            if page.url != initial_url:
                logger.success("✅ 'Proceed' click triggered navigation (AgentQL)")
                return True
                
            # Retry with force click
            logger.warning("JS click didn't navigate, retrying with force click...")
            btn.click(force=True)
            time.sleep(2)
            
            if page.url != initial_url:
                return True
                
            return True # Assume success if no error
            
    except Exception as e:
        logger.debug(f"AgentQL intent button failed: {e}")

    # 2. Fallback: Try direct selectors
    intent_selectors = [
        "button:has-text('Proceed to create an account')",
        "span:has-text('Proceed to create an account')",
        "#createAccountSubmit",
        "input[type='submit'][value*='create']",
        "a:has-text('Proceed to create an account')",
    ]
    
    for selector in intent_selectors:
        try:
            btn = page.locator(selector).first
            if btn.is_visible(timeout=1000):
                logger.info(f"Walking fallback selector: {selector}")
                device.scroll_to_element(btn, "Proceed Button")
                
                # Try JS click
                device.js_click(btn, f"Proceed Button ({selector})")
                time.sleep(2)
                
                if page.url != initial_url:
                     logger.success(f"✅ 'Proceed' click triggered navigation ({selector})")
                     return True
                
                # Retry with force click
                logger.warning(f"JS click ({selector}) didn't navigate, retrying force click...")
                btn.click(force=True)
                time.sleep(2)
                
                if page.url != initial_url:
                    return True
                    
                return True
        except:
            continue
            
    return False


def click_create_account(page, device: DeviceAdapter = None) -> bool:
    """
    Click the "Create account" option on the sign-in page.
    
    Args:
        page: Playwright page object
        device: DeviceAdapter instance
        
    Returns:
        True if successfully clicked
    """
    if device is None:
        device = DeviceAdapter(page)
    
    # Method 1: Check known choice indicators
    try:
        # Check for radio buttons or specific create button
        if page.locator("input[name='create'][type='radio']").first.is_visible(timeout=500) or \
           page.locator("#createAccountSubmit").first.is_visible(timeout=500) or \
           page.locator("#auth-create-account-link").first.is_visible(timeout=500) or \
           page.locator("button:has-text('Create account')").first.is_visible(timeout=500):
            logger.info("Found Create Account option via direct indicator")
            # Proceed with normal click logic...
            pass
        else:
            # Maybe a popup is blocking?
            from amazon.actions.interstitials import handle_generic_popups
            if handle_generic_popups(page, device):
                time.sleep(1)
            
            # Fallback check: maybe we are already on an email entry page?
            from amazon.actions.signin_email import is_email_signin_page
            if is_email_signin_page(page):
                logger.info("Already on simple email entry page, no need to click Create Account")
                return True
    except:
        pass

    logger.info("Looking for Create Account option...")

    # Method 0: Check for "Welcome" radio button page (Variant 1)
    # This page demands selecting a radio button then clicking Continue
    try:
        # Look for the specific label text "Create account. New to Amazon?"
        create_label = page.locator("label:has-text('Create account')").first
        create_radio = page.locator("input[type='radio'][name='create']").first
        
        if create_label.is_visible(timeout=1000) or create_radio.is_visible(timeout=1000):
            logger.info("Detected 'Welcome' radio button choice page")
            
            # Click the radio button (label or input)
            if create_radio.is_visible():
                device.tap(create_radio, "Create Account radio")
            elif create_label.is_visible():
                # Try to find the radio input associated with this label if possible
                try:
                    # Sometimes finding the input is better than clicking label
                    associated_id = create_label.get_attribute("for")
                    if associated_id:
                         page.locator(f"#{associated_id}").click()
                    else:
                         device.tap(create_label, "Create Account label")
                except:
                     device.tap(create_label, "Create Account label (fallback)")
                
            time.sleep(1.0) # Wait for UI update

            
            # Now finding and clicking Continue is MANDATORY
            continue_btn = page.locator("input#continue, #continue, input[type='submit']").first
            if continue_btn.is_visible(timeout=2000):
                logger.info("Clicking Continue to proceed to registration...")
                device.tap(continue_btn, "Continue button")
                time.sleep(random.uniform(*DELAYS["after_click"]))
                return True
    except Exception as e:
        logger.debug(f"Welcome page check failed: {e}")

    
    # Method 1: Multi-priority approach via AgentQL helper (Cache -> AgentQL)
    try:
        from amazon.agentql_helper import query_amazon
        results = query_amazon(page, "signin_page", cache=True)
        
        if 'create_account_option' in results and results['create_account_option']['element']:
            element_data = results['create_account_option']
            element = element_data['element']
            
            logger.info("🆕 Clicking Create Account via prioritized approach...")
            
            device.scroll_to_element(element, "Create Account")
            time.sleep(random.uniform(0.3, 0.8))
            
            # Try clicking
            try:
                element.click()
                time.sleep(random.uniform(*DELAYS["after_click"]))
                return True
            except:
                element.evaluate("el => el.click()")
                return True
            
    except Exception as e:
        logger.warning(f"Prioritized approach failed: {e}")
    
    # Fallback: Try direct selectors
    logger.info("Trying selector fallback...")
    try:
        # Try various selectors for create account
        # Try various selectors for create account
        # EXCLUDE "business" to avoid "Create a free business account"
        selectors = [
            "input[type='radio'][name='create']",  # Radio button
            "#createAccountSubmit",  # Submit button
            "#auth-create-account-link", # Standard login page Creation button
            "a:has-text('Create account'):not(:has-text('business'))",  # Link, excluding business
            "label:has-text('Create account')",  # Label
            "[data-action='create-account-action']",  # Data attribute
            "input[value*='Create']",  # Input with Create
            "span:has-text('Create your Amazon account')",
        ]
        
        for selector in selectors:
            try:
                element = page.locator(selector).first
                if element.is_visible():
                    logger.info(f"Found element with selector: {selector}")
                    device.scroll_to_element(element, "Create Account")
                    time.sleep(random.uniform(0.3, 0.6))
                    element.click()
                    time.sleep(random.uniform(*DELAYS["after_click"]))
                    logger.success("✓ Create Account clicked via selector")
                    return True
            except:
                continue
                
    except Exception as e:
        logger.warning(f"Selector fallback failed: {e}")
    
    # Final fallback: JS click on any element containing "Create account"
    logger.info("Trying JS text-based click...")
    try:
        result = page.evaluate("""
            () => {
                // 1. Look for radio button and its label
                const createAccountRadio = document.querySelector('input[type="radio"][name="create"]');
                if (createAccountRadio) {
                    createAccountRadio.click();
                    // Also try to find the submit button and click it after selection
                    const submitBtn = document.querySelector('#createAccountSubmit') || document.querySelector('input[type="submit"]');
                    if (submitBtn) {
                        setTimeout(() => submitBtn.click(), 500);
                        return 'radio_and_submit_clicked';
                    }
                    return 'radio_clicked';
                }

                // 2. Find any clickable element with "Create account" text
                const elements = document.querySelectorAll('label, a, button, input, span, div');
                for (const el of elements) {
                    if (el.textContent && el.textContent.includes('Create account')) {
                        // ... existing logic ...
                        const forId = el.getAttribute('for');
                        if (forId) {
                            const input = document.getElementById(forId);
                            if (input) {
                                input.click();
                                return 'clicked_input';
                            }
                        }
                        el.click();
                        return 'clicked_element';
                    }
                }
                return null;
            }
        """)
        
        if result:
            logger.success(f"✓ Create Account clicked via JS: {result}")
            time.sleep(1.5) # Wait for potential redirect
            return True
            
    except Exception as e:
        logger.warning(f"JS fallback failed: {e}")
    
    logger.error("Could not find Create Account option")
    return False


def fill_registration_form(page, identity, device: DeviceAdapter = None) -> bool:
    """
    Fill out the Amazon registration form.
    
    Args:
        page: Playwright page object
        identity: Identity object or dict containing user info:
            - name: Full name (or firstname + lastname)
            - email: Email address
            - password: Password to use
        device: DeviceAdapter instance
        
    Returns:
        True if form filled successfully
    """
    if device is None:
        device = DeviceAdapter(page)
    
    # Handle both Identity objects and dicts
    if hasattr(identity, 'to_dict'):
        identity_data = identity.to_dict()
    else:
        identity_data = identity
    
    full_name = identity_data.get('name') or f"{identity_data.get('firstname', '')} {identity_data.get('lastname', '')}".strip()
    email = identity_data.get('email', '')
    password = identity_data.get('password', '')
    
    logger.info(f"Filling registration form for: {email}")
    
    filled_fields = []  # Track which fields were successfully filled
    
    # CSS selectors for registration form fields (faster than AgentQL)
    css_field_map = {
        'name': ('#ap_customer_name', full_name),
        'email': ('#ap_email', email),
        'password': ('#ap_password', password),
        'password_check': ('#ap_password_check', password)
    }
    
    for field, (selector, value) in css_field_map.items():
        try:
            element = page.locator(selector).first
            if element.is_visible(timeout=500):
                # Check if field already has the correct value
                try:
                    current_value = element.input_value()
                    if current_value == value:
                        logger.debug(f"Field {field} already has correct value, skipping")
                        filled_fields.append(field)
                        continue
                except:
                    pass
                
                logger.info(f"📝 Entering {field}...")
                element.fill("")  # Clear first
                time.sleep(0.1)
                device.type_text(element, value, field)
                filled_fields.append(field)
        except Exception as e:
            logger.debug(f"CSS selector {selector} failed: {e}")
    
    if len(filled_fields) >= 3:
        logger.success(f"✓ Registration form filled ({len(filled_fields)} fields)")
        time.sleep(0.5)  # Brief pause before clicking submit
        return True
    
    # Fallback to AgentQL only if CSS didn't work
    logger.info("🔄 Trying AgentQL for remaining fields...")
    from amazon.agentql_helper import query_amazon
    results = query_amazon(page, "registration_form", cache=True)
    
    if results:
        field_map = {
            'name': ('name_input', full_name),
            'email': ('email_input', email),
            'password': ('password_input', password),
            'password_check': ('password_confirm_input', password)
        }
        
        for field, (key, value) in field_map.items():
            if field in filled_fields:
                continue  # Already filled via CSS
            if key in results:
                try:
                    element = results[key]['element']
                    # Check if already filled
                    try:
                        if element.input_value() == value:
                            filled_fields.append(field)
                            continue
                    except: pass
                    
                    logger.info(f"📝 Entering {field} via AgentQL...")
                    element.fill("")
                    time.sleep(0.1)
                    device.type_text(element, value, field)
                    filled_fields.append(field)
                except Exception as e:
                    logger.debug(f"Failed to fill {field} via AgentQL: {e}")

    if len(filled_fields) >= 3:
        logger.success(f"✓ Registration form filled ({len(filled_fields)} fields)")
        return True
    else:
        logger.error(f"Only filled {len(filled_fields)} fields: {filled_fields}")
        return False


def click_continue_registration(page, device: DeviceAdapter = None) -> bool:
    """
    Click the Verify email or Continue button on registration form.
    """
    if device is None:
        device = DeviceAdapter(page)
    
    logger.info("Clicking Verify email / Continue...")
    initial_url = page.url
    
    # Method 1: Direct CSS selectors FIRST (faster than AgentQL)
    css_selectors = [
        "input[type='submit'][value='Verify email']",
        "input#continue[type='submit']",
        "input[type='submit'][value*='Verify']",
        "input[type='submit'][value*='Continue']",
        "button:has-text('Verify email')",
        "button:has-text('Continue')",
        "#continue",
        "form input[type='submit']",
    ]
    
    for selector in css_selectors:
        try:
            btn = page.locator(selector).first
            if btn.is_visible(timeout=500):
                logger.info(f"Found button via: {selector}")
                device.scroll_to_element(btn, "Submit Button")
                time.sleep(0.2)
                
                # Use JS click for reliability
                device.js_click(btn, f"Submit Button ({selector})")
                time.sleep(1.5)
                
                # Check for state change
                new_url = page.url
                if new_url != initial_url:
                    logger.success(f"✓ Form submitted, URL changed ({selector})")
                    return True
                    
                # Check if we moved to verification or error state
                try:
                    if (page.locator("text='Enter the code'").first.is_visible(timeout=500) or
                        page.locator("text='Verify email address'").first.is_visible(timeout=500) or
                        page.locator("input[name='code']").first.is_visible(timeout=500) or
                        page.locator("#cvf-input-code").first.is_visible(timeout=500)):
                        logger.success("✓ Verification page detected")
                        return True
                except:
                    pass
                
                # Retry with force click if JS click didn't navigate
                logger.warning(f"JS click ({selector}) didn't navigate, retrying with force click...")
                try:
                    btn.click(force=True)
                    time.sleep(1.5)
                    if page.url != initial_url:
                        return True
                except:
                    pass
        except Exception as e:
            logger.debug(f"Selector {selector} failed: {e}")
            continue
    
    # Method 2: XPath selectors
    xpath_selectors = [
        "//input[@type='submit' and @value='Verify email']",
        "//input[@id='continue' and @type='submit']",
        "//input[@type='submit' and contains(@value, 'Verify')]",
        "//input[@type='submit' and contains(@value, 'Continue')]",
        "//form//input[@type='submit']",
    ]
    
    for xpath in xpath_selectors:
        try:
            element = page.locator(f"xpath={xpath}").first
            if element.is_visible(timeout=300):
                logger.info(f"Clicking via XPath: {xpath[:40]}...")
                device.scroll_to_element(element, "Button")
                
                # Use JS click
                device.js_click(element, f"Button ({xpath})")
                time.sleep(1.5)
                
                if page.url != initial_url:
                    return True
                
                # Retry with force click
                logger.warning(f"JS click ({xpath}) didn't navigate, retrying with force click...")
                try:
                    element.click(force=True)
                    time.sleep(1.5)
                    if page.url != initial_url:
                        return True
                except:
                    pass
        except:
            continue
    
    # Method 3: JS click fallback - directly find and click the submit button
    logger.info("Trying JS click fallback...")
    try:
        result = page.evaluate("""
            () => {
                // Find visible submit button
                const submitBtns = document.querySelectorAll('input[type="submit"], button[type="submit"]');
                for (const btn of submitBtns) {
                    if (btn.offsetParent !== null && btn.value && 
                        (btn.value.includes('Verify') || btn.value.includes('Continue'))) {
                        btn.click();
                        return 'clicked: ' + btn.value;
                    }
                }
                // Fallback: any visible submit in form
                const form = document.querySelector('form');
                if (form) {
                    const submit = form.querySelector('input[type="submit"]');
                    if (submit && submit.offsetParent !== null) {
                        submit.click();
                        return 'clicked form submit';
                    }
                }
                return null;
            }
        """)
        if result:
            logger.success(f"✓ Button clicked via JS: {result}")
            time.sleep(1.5)
            if page.url != initial_url:
                return True
            # Check content change
            try:
                if page.locator("input[name='code'], #cvf-input-code").first.is_visible(timeout=1000):
                    return True
            except:
                pass
    except Exception as e:
        logger.debug(f"JS click failed: {e}")
    
    # Method 4: AgentQL as last resort
    try:
        from amazon.agentql_helper import query_amazon
        results = query_amazon(page, "registration_form", cache=True)
        for key in ['continue_button', 'create_account_button']:
            if key in results and results[key].get('element'):
                btn = results[key]['element']
                btn.click()
                time.sleep(1.5)
                if page.url != initial_url:
                    return True
    except:
        pass
            
    logger.warning("Could not click Verify/Continue button")
    return page.url != initial_url


def detect_signup_state(page) -> str:
    """
    Detect current state in signup flow.
    
    Returns:
        'signin_choice': On page with Create account / Sign in options
        'registration_form': On the registration form
        'verification': Verification code needed
        'captcha': CAPTCHA challenge
        'passkey_nudge': Passkey setup request
        'success': Registration complete
        'error': Error state
        'unknown': Unknown state
    """
    url = page.url.lower()
    logger.debug(f"Detecting state for URL: {url}")
    
    try:
        # Check URL patterns first - ORDER MATTERS!
        
        # Check for CAPTCHA first via content (sometimes URL is ambiguous)
        try:
            from amazon.captcha_solver import is_captcha_present
            if is_captcha_present(page).get('present'):
                return "captcha"
        except:
            pass
        
        # Check verification FIRST (most important to not miss)
        if ("/ap/cvf" in url or "verification" in url or "otp" in url) and "/ap/signin" not in url:
            logger.debug("URL matches verification pattern")
            return "verification"
        
        # Check captcha
        if "/ap/challenge" in url or "captcha" in url:
            return "captcha"
            
        # Check for puzzle (Funcaptcha)
        # URL usually contains /ap/cvf/request?arb=...
        if "arb=" in url:
            logger.debug("URL matches puzzle pattern (arb parameter)")
            return "puzzle"
        
        try:
            if page.locator("text='Solve this puzzle'").first.is_visible(timeout=500):
                logger.debug("Puzzle text detected")
                return "puzzle"
        except:
            pass

        
        # Check passkey nudge
        if "/claim/webauthn/nudge" in url or "webauthn" in url:
            logger.debug("URL matches passkey nudge pattern")
            return "passkey_nudge"
        
        # Check success
        if "/gp/yourstore" in url or "/homepage" in url or "ref=nav_ya_signin" in url:
            return "success"
        
        # Check registration form
        if "/ap/register" in url:
            return "registration_form"
            
        # Check for new customer intent (Variant 2 follow-up)
        if "/ax/claim/intent" in url:
            return "new_customer_intent"
            
        if "/ap/signin" in url:
            logger.debug("URL matches /ap/signin")
            
            # 1. Check for signin_choice (Variant 1) - PRIORITIZED
            try:
                # If radio buttons OR "Create account" button is visible OR "No account found" warning
                # STICTER CHECK: Welcome header is NOT enough on its own anymore, as "Welcome to Amazon" appears on signin pages too.
                # Must find the radio choice OR the "New to Amazon" button.
                if (page.locator("input[name='create'][type='radio']").first.is_visible(timeout=500) or 
                    page.locator("label:has-text('Create account')").first.is_visible(timeout=500) or
                    page.locator("#createAccountSubmit").first.is_visible(timeout=500) or
                    page.locator("button:has-text('Create account')").first.is_visible(timeout=500) or
                    page.locator("input[type='submit'][value*='Create account']").first.is_visible(timeout=500) or
                    page.locator("text='No account found'").first.is_visible(timeout=500)):
                    logger.debug("Signin choice indicators detected (Specific)")
                    return "signin_choice"
                    
                # Specific check for "Welcome" variant 1 (MUST have radio or specific structure)
                # If we see "Welcome" AND "New to Amazon?", it's the choice page.
                if (page.locator("h1:has-text('Welcome')").first.is_visible(timeout=200) or page.locator("span:has-text('Welcome')").first.is_visible(timeout=200)):
                     if page.locator("text='New to Amazon?'").first.is_visible(timeout=200):
                         logger.debug("Welcome + New to Amazon detected")
                         return "signin_choice"
            except:
                pass
            
            # 2. Check for email entry page (simple sign in / Variant 2)
            try:
                from amazon.actions.signin_email import is_email_signin_page
                if is_email_signin_page(page):
                    logger.debug("Detected email signin entry page (Variant 2)")
                    return "email_signin_entry"
            except Exception as e:
                logger.debug(f"Email signin check failed: {e}")

            # 3. Check for INLINE registration form (Very common after "No account found")
            try:
                # Use slightly longer timeout as page might be animating
                name_field = page.locator("#ap_customer_name, input[name='customerName']").first
                password_field = page.locator("#ap_password, input[name='password']").first
                
                if name_field.is_visible(timeout=1000) or password_field.is_visible(timeout=1000):
                    logger.debug("Inline registration form elements visible")
                    return "registration_form"
            except:
                pass
            
            return "signin"
        
        # If URL didn't match, try page content detection
        logger.debug("URL didn't match known patterns, checking page content...")
        
        # Keep original content-based checks
        try:
            if (page.locator("input[name='customerName']").first.is_visible(timeout=500) or 
                page.locator("#ap_customer_name").first.is_visible(timeout=500) or
                page.locator("text=Create your Amazon account").first.is_visible(timeout=500)):
                return "registration_form"
        except:
            pass
        
        try:
            if (page.locator("text=Create account").first.is_visible(timeout=1000) or
                page.locator("input[name='create']").first.is_visible(timeout=500)):
                return "signin_choice"
        except:
            pass

        # Check for new customer intent via content
        try:
            if (page.locator("text=Looks like you're new to Amazon").first.is_visible(timeout=500) or
                page.locator("button:has-text('Proceed to create an account')").first.is_visible(timeout=500)):
                return "new_customer_intent"
        except:
            pass
            
        # Check for verification page
        try:
            if (page.locator("text=Enter the code").first.is_visible(timeout=500) or
                page.locator("text=Enter security code").first.is_visible(timeout=500) or
                page.locator("text=Verify email address").first.is_visible(timeout=500) or
                page.locator("input[name='code']").first.is_visible(timeout=500) or
                page.locator("#cvf-input-code").first.is_visible(timeout=500)):
                return "verification"
        except:
            pass
            
        # Check for passkey nudge
        try:
            if (page.locator("text='Use face ID, fingerprint, or PIN to sign in'").first.is_visible(timeout=500) or
                page.locator("text='Set up a passkey'").first.is_visible(timeout=500) or
                page.locator("#passkey-nudge-skip-button").first.is_visible(timeout=500)):
                return "passkey_nudge"
        except:
            pass
            
        # Check for Add mobile number
        try:
            if (page.locator("text='Add mobile number'").first.is_visible(timeout=500) or
                page.locator("h1:has-text('Add mobile number')").first.is_visible(timeout=500) or
                page.locator("input[name='cvf_phone_num']").first.is_visible(timeout=500)):
                return "add_mobile"
        except:
            pass
        
        # Check for sign-in form (email input only)
        try:
            if (page.locator("text=Sign in").first.is_visible(timeout=1000) and
                page.locator("input[name='email']").first.is_visible(timeout=500)):
                return "signin_choice"
        except:
            pass
        
        # Try AgentQL for comprehensive detection
        try:
            from amazon.agentql_helper import query_amazon
            # Use small cache or no cache to get fresh state
            results = query_amazon(page, "signin_page", cache=False)
            
            if 'create_account_option' in results and results['create_account_option']['element']:
                return "signin_choice"
            
            # Check for registration form fields via AgentQL logic manually or use registration_form query
            results_reg = query_amazon(page, "registration_form", cache=False)
            if 'name_input' in results_reg and results_reg['name_input']['element']:
                return "registration_form"
                
        except:
            pass
            
    except Exception as e:
        logger.debug(f"State detection error: {e}")
    
    return "unknown"
