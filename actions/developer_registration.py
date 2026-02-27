"""
Amazon Developer Registration Flow V2
Includes robust React-aware dropdown handling and state machine orchestration.
"""
import time
from loguru import logger
from amazon.core.session import SessionState
from amazon.core.interaction import InteractionEngine
from amazon.utils.xpath_cache import get_cached_xpath, extract_and_cache_xpath
import agentql

REGISTRATION_URL = "https://developer.amazon.com/settings/console/registration?return_to=/settings/console/home"

def _safe_is_visible(locator, timeout=500) -> bool:
    """Safe visibility check that never raises Patchright locator errors."""
    try:
        # Avoid .first if possible as it triggers 'Can't query n-th element' in some cases
        return locator.is_visible(timeout=timeout)
    except Exception:
        return False

def detect_dev_state(page) -> str:
    """Detect current state of the developer registration flow."""
    if page.is_closed():
        return "unknown"
        
    url = page.url.lower()
    
    # 1. Success / Identity Verification (Post-registration)
    # Success markers: Console Home, IDV Landing, or Dashboard indicators
    # We strip the query params to avoid false positives from 'return_to' parameters in the registration URL
    base_url = url.split('?')[0]
    is_on_home = "/settings/console/home" in base_url or "/idv/landing_page" in base_url or "console/home" in base_url
    
    # Dashboard indicators should be specific to the post-registration view
    has_dashboard_indicators = _safe_is_visible(page.get_by_text("Identity Verification"), timeout=500) or \
                               _safe_is_visible(page.get_by_text("Your apps"), timeout=500)
                               
    has_registration_indicators = _safe_is_visible(page.get_by_text("Registration"), timeout=500) or \
                                  _safe_is_visible(page.locator("#company_name"), timeout=500)

    # Success if we are on the home path OR we see dashboard content and NOT registration content
    if is_on_home or (has_dashboard_indicators and not has_registration_indicators):
        # Additional safety: if the path still contains '/registration', it's NOT a success yet
        if "/registration" in base_url:
            return "registration_form"
        return "success"
        
    # 2. 2FA Authenticator Prompt
    if _safe_is_visible(page.get_by_text("Enroll a 2-Step Verification authenticator"), timeout=500) or \
       _safe_is_visible(page.get_by_text("Use an authenticator app"), timeout=500):
        return "2fa_prompt"
        
    # 3. Address Clarification Interstitial
    if "clarification" in url or "invalid-address" in url:
        return "address_clarification"

    # 4. Registration Form
    # Strict check: URL must contain 'registration' but NOT 'idv' or 'clarification'
    if ("/registration" in base_url and "/idv/" not in base_url) or _safe_is_visible(page.locator("#company_name"), timeout=500):
        return "registration_form"
        
    return "unknown"

def run_developer_registration(playwright_page, session: SessionState, device) -> bool:
    """State-machine driven Developer Registration."""
    logger.info("🔄 Starting V2 Developer Registration Flow...")
    
    # User Request: Use a new tab and close the old one to avoid TargetClosedError
    try:
        logger.info("🆕 Switching to fresh tab for Developer Registration...")
        context = playwright_page.context
        new_page = context.new_page()
        if playwright_page and not playwright_page.is_closed():
            # Try to close, but don't crash if it fails
            try: playwright_page.close()
            except: pass
        playwright_page = new_page
        device.page = playwright_page
    except Exception as e:
        logger.warning(f"Could not recycle tab: {e}")

    interaction = InteractionEngine(playwright_page, device)
    
    if not session.identity:
        logger.error("No identity in session for Developer Registration")
        return False
        
    identity = session.identity
    
    max_steps = 10
    for step in range(max_steps):
        if playwright_page.is_closed():
            logger.warning("Tab closed unexpectedly in state loop. Re-acquiring...")
            try:
                playwright_page = playwright_page.context.new_page()
                device.page = playwright_page
                interaction = InteractionEngine(playwright_page, device)
            except:
                logger.error("Failed to re-acquire tab.")
                return False

        state = detect_dev_state(playwright_page)
        logger.info(f"👨‍💻 Developer Flow State: {state}")
        
        if state == "success":
            logger.success("✅ Developer Registration successful!")
            session.update_flag("dev_registration", True)
            return True
            
        elif state == "unknown":
            logger.info(f"Navigating to: {REGISTRATION_URL}")
            try:
                playwright_page.goto(REGISTRATION_URL, wait_until="domcontentloaded", timeout=30000)
            except Exception as e:
                logger.error(f"Navigation failed: {e}")
            time.sleep(3)
            
        elif state == "2fa_prompt":
            logger.warning("🔒 2-Step Verification required. Please scan QR manually.")
            # We pause and wait for user, or until URL changes
            for _ in range(60): # 10 minutes max
                if playwright_page.is_closed(): return False
                curr_state = detect_dev_state(playwright_page)
                if curr_state != "2fa_prompt":
                    break
                time.sleep(10)

        elif state == "address_clarification":
            logger.info("📍 Handling Address Clarification...")
            # Try to just click 'Use this address' if it exists
            # Or navigate away to registration if stuck
            success = interaction.smart_click(
                "Use suggested address",
                selectors=["input[name='useSelectedAddress']", "#useSelectedAddress", "button:has-text('Use this address')"],
                agentql_query="{ use_suggested_address_button }",
                cache_key="dev_reg_address_clarify"
            )
            if not success:
                logger.warning("Could not clear address clarification. Forcing navigation...")
                playwright_page.goto(REGISTRATION_URL)
            time.sleep(3)
                
        elif state == "registration_form":
            logger.info("📋 Discovering registration form elements...")
            
            # Discovery Keys & Query Mapping
            discovery_map = {
                "country_input": "dev_reg_country_input",
                "customer_facing_business_name": "dev_reg_business_name",
                "address_line_1": "dev_reg_address_line1",
                "city_input": "dev_reg_city",
                "postal_code_zip_code": "dev_reg_zip",
                "state_province": "dev_reg_state",
                "same_as_primary_email_address_checkbox": "dev_reg_same_as_cb",
                "phone_number_code_input": "dev_reg_phone_prefix",
                "phone_number_input": "dev_reg_phone_num"
            }
            
            # 1. Try to load from Cache first
            form_elements = {}
            needs_discovery = False
            
            for attr, cache_key in discovery_map.items():
                xpath = get_cached_xpath(cache_key)
                if xpath:
                    loc = playwright_page.locator(f"xpath={xpath}").first
                    if _safe_is_visible(loc, timeout=1000):
                        form_elements[attr] = loc
                    else:
                        needs_discovery = True # Cache out of date or element moved
                else:
                    needs_discovery = True
            
            # 2. Sequential Discovery fallback via SINGLE AgentQL Query
            if needs_discovery:
                logger.info("📡 Cache incomplete. Performing single AgentQL discovery query...")
                discovery_query = """
                {
                    country_input,
                    customer_facing_business_name,
                    address_line_1,
                    city_input,
                    postal_code_zip_code,
                    state_province,
                    same_as_primary_email_address_checkbox_label,
                    phone_number_code_input,
                    phone_number_input
                }
                """
                try:
                    aql_page = agentql.wrap(playwright_page)
                    response = aql_page.query_elements(discovery_query)
                    
                    # Process and Cache all results
                    for attr, cache_key in discovery_map.items():
                        element = getattr(response, attr, None)
                        if element:
                            form_elements[attr] = element
                            extract_and_cache_xpath(element, cache_key)
                except Exception as e:
                    logger.error(f"AgentQL discovery failed: {e}")

            # Define helper to get element safely
            def get_el(name): return form_elements.get(name)

            def safe_fill(name, value, fallback_selector=None):
                """Fills a field with retry logic for React detachment."""
                if not value: return False
                logger.info(f"Filling {name}...")
                
                # Check cache/form_elements first
                el = get_el(name)
                
                # Try three times to handle detachment
                for attempt in range(3):
                    try:
                        target = el
                        if attempt > 0 or not target:
                            # Re-query if stale or first attempt failed
                            if fallback_selector:
                                target = playwright_page.locator(fallback_selector).first
                            else:
                                # If no fallback selector, and el is None or stale, we can't fill
                                continue
                        
                        if target and _safe_is_visible(target, timeout=2000):
                            target.fill("")
                            target.fill(str(value))
                            time.sleep(0.1) # Small delay after fill
                            return True
                    except Exception as e:
                        if attempt == 2:
                            logger.warning(f"Failed to fill {name} after retries: {e}")
                        time.sleep(0.5)
                return False

            def click_first_dropdown_option(page, target_val=None, priority_selectors=None):
                """Helper to click the first visible option in a React-style dropdown."""
                time.sleep(1.5) # Wait for dropdown animation
                
                # Use provided priority selectors first, then generic fallbacks
                search_selectors = (priority_selectors or []) + [
                    "div[role='option']", 
                    "li[role='option']",
                    ".sc-caSCKo .sc-eqIVtm",
                    "xpath=//*[contains(@class, 'flinDQ')]//div",
                    "[class*='MenuList'] div",
                    "[class*='option']"
                ]
                
                for sel in search_selectors:
                    try:
                        locators = page.locator(sel)
                        count = locators.count()
                        if count == 0: continue
                        
                        # Gather all visible matching options
                        candidates = []
                        for i in range(count):
                            opt = locators.nth(i)
                            if _safe_is_visible(opt, timeout=300):
                                text = opt.inner_text().strip()
                                
                                # Scoring: 
                                # exact match = 100
                                # starts with + space/opener = 80
                                # contains = 50
                                score = 0
                                if not target_val:
                                    score = 1
                                else:
                                    t_lower = target_val.lower()
                                    text_lower = text.lower()
                                    if text_lower == t_lower: score = 100
                                    elif text_lower.startswith(t_lower + " ("): score = 90
                                    elif text_lower.startswith(t_lower + " "): score = 80
                                    elif t_lower in text_lower: score = 50
                                
                                if score > 0:
                                    candidates.append((score, opt, text))
                        
                        # Sort by score descending and take the first one
                        if candidates:
                            candidates.sort(key=lambda x: x[0], reverse=True)
                            best_score, best_opt, best_text = candidates[0]
                            
                            logger.info(f"✓ Found best option: '{best_text}' (score: {best_score}, selector: {sel[:30]}). Clicking...")
                            
                            best_opt.evaluate("""el => {
                                el.scrollIntoView();
                                const events = ['mousedown', 'click', 'mouseup'];
                                events.forEach(name => {
                                    el.dispatchEvent(new MouseEvent(name, {
                                        bubbles: true,
                                        cancelable: true,
                                        view: window
                                    }));
                                });
                            }""")
                            return True
                    except Exception:
                        continue
                return False

            # 3. Country Selection (React Styled Dropdown)
            logger.info(f"Filling Country: {identity.country}...")
            try:
                country_input = get_el("country_input")
                
                if country_input:
                    logger.info("⚡ Using JS click for country input...")
                    try:
                        # Use JS click to avoid Playwright hang
                        playwright_page.evaluate("el => el.click()", country_input)
                    except:
                        playwright_page.evaluate("document.querySelector('#country_code')?.focus()")
                    
                    time.sleep(0.3)
                    
                    try:
                        # Force focus and type
                        country_input.focus()
                        country_input.fill("") 
                        country_input.type(identity.country, delay=35)
                    except:
                        playwright_page.keyboard.type(identity.country, delay=35)
                    
                    country_priority = [
                        "xpath=/html/body/div/div[2]/div/div/div[2]/div[2]/div[3]/div/div[3]/div/div/div[2]/div/div[1]/div[1]",
                        "xpath=//*[@id='root']/div/div[2]/div[2]/div[3]/div/div[3]/div/div/div[2]/div/div[1]/div[1]"
                    ]
                    if not click_first_dropdown_option(playwright_page, identity.country, priority_selectors=country_priority):
                        logger.warning("Could not find country in dropdown, pushing Enter...")
                        playwright_page.keyboard.press("ArrowDown")
                        playwright_page.keyboard.press("Enter")
                time.sleep(1)
            except Exception as e:
                logger.warning(f"Error selecting country: {e}")
            
            # 4. Text Fields with fallbacks
            safe_fill("customer_facing_business_name", identity.full_name, "#company_name")
            safe_fill("address_line_1", identity.address_line1, "#address_line")
            safe_fill("city_input", identity.city, "#city")
            safe_fill("postal_code_zip_code", identity.zip_code, "#postal_code")
            safe_fill("state_province", identity.state, "#state_province")
            
            # 5. Checkbox
            cb = get_el("same_as_primary_email_address_checkbox_label")
            try:
                if cb:
                    logger.info("Clicking 'Same as primary' checkbox (Robust JS)...")
                    cb.evaluate("""el => {
                        const events = ['mousedown', 'click', 'mouseup'];
                        events.forEach(name => el.dispatchEvent(new MouseEvent(name, {bubbles: true, cancelable: true, view: window})));
                    }""")
                    time.sleep(1)
                else:
                    logger.info("Falling back to standard label selector for checkbox...")
                    playwright_page.evaluate("""() => { 
                        const el = Array.from(document.querySelectorAll('label')).find(l => l.innerText.includes('Same as')); 
                        if(el) {
                           const events = ['mousedown', 'click', 'mouseup'];
                           events.forEach(name => el.dispatchEvent(new MouseEvent(name, {bubbles: true, cancelable: true, view: window})));
                        }
                    }""")
                    time.sleep(1)
            except Exception as e:
                logger.warning(f"Failed to click checkbox: {e}")
            
            # 6. Phone Prefix Dropdown
            try:
                country_abbrev = getattr(identity, 'country_code', 'AU') # Default to AU for this case
                phone_prefix_input = get_el("phone_number_code_input")
                
                if phone_prefix_input:
                    logger.info("⚡ Using JS click to open phone prefix...")
                    phone_prefix_input.evaluate("el => el.click()")
                    time.sleep(0.5)
                    
                    try:
                        phone_prefix_input.focus()
                        phone_prefix_input.fill("")
                        phone_prefix_input.type(country_abbrev, delay=40)
                    except:
                        playwright_page.keyboard.type(country_abbrev, delay=40)
                        
                    phone_priority = [
                        "xpath=//*[@id='root']/div/div[2]/div[4]/div[7]/div/div[3]/div/div[1]/div[2]/div/div[1]/div[1]"
                    ]
                    if not click_first_dropdown_option(playwright_page, country_abbrev, priority_selectors=phone_priority):
                        logger.warning("Could not find phone prefix option in dropdown, using Enter...")
                        playwright_page.keyboard.press("ArrowDown")
                        playwright_page.keyboard.press("Enter")
                    else:
                        logger.info(f"✓ Phone prefix selected: {country_abbrev}")
                            
            except Exception as e:
                logger.error(f"Phone prefix error: {e}")
            
            # 7. Phone Number
            num_el = get_el("phone_number_input")
            if num_el:
                try:
                    logger.info(f"Filling Phone Number: {identity.phone}")
                    num_el.fill(identity.phone)
                except Exception as e:
                    logger.warning(f"Failed to fill phone: {e}")
                
            # 8. Submit
            logger.info("🚀 Submitting Developer Registration...")
            
            # User Request: Force click the button from the first try
            # We prioritize direct Playwright force behavior over JS click for this specific step
            force_selectors = [
                 "xpath=//*[@id='registrationSubmit']",
                 "#registrationSubmit",
                 "button:has-text('Agree and Continue')",
                 "button:has-text('Submit')"
            ]
            
            success = False
            for sel in force_selectors:
                try:
                    btn = playwright_page.locator(sel).first
                    if _safe_is_visible(btn, timeout=1000):
                        logger.info(f"⚡ Trigerring submission via {sel} (Composite JS)...")
                        # 1. Direct JS Click
                        btn.evaluate("el => el.click()")
                        # 2. Multi-event dispatch (React)
                        btn.evaluate("""el => {
                            const events = ['mousedown', 'click', 'mouseup', 'pointerdown', 'pointerup'];
                            events.forEach(name => {
                                el.dispatchEvent(new (name.startsWith('pointer') ? PointerEvent : MouseEvent)(name, {
                                    bubbles: true,
                                    cancelable: true,
                                    view: window,
                                    buttons: 1
                                }));
                            });
                        }""")
                        # 3. Direct Playwright Force Click (Fallback for persistent overlays)
                        try:
                            btn.click(force=True, timeout=1500)
                        except: pass
                        time.sleep(1)
                        success = True
                        break
                except Exception:
                    continue

            if not success:
                # Fallback to the high-powered Interaction Engine with Cache and AgentQL Fallback
                success = interaction.smart_click(
                    "Submit Registration",
                    selectors=[
                        "#registrationSubmit", 
                        "xpath=//*[@id='registrationSubmit']",
                        "button:has-text('Agree and Continue')",
                        "button:has-text('Submit')"
                    ],
                    agentql_query="{ submit_btn }",
                    cache_key="dev_registration_submit",
                    biomechanical=True
                )
            
            if not success:
                logger.error("❌ Final submission failed after all waterfall attempts.")
            
            # Monitoring for transition
            logger.info("⏳ Waiting for registration to process...")
            
            # Check for immediate validation errors
            time.sleep(2)
            error_locator = playwright_page.locator("[class*='error'], .errorMessage, [role='alert']").first
            if _safe_is_visible(error_locator, timeout=500):
                logger.error(f"❌ Form validation error detected: {error_locator.inner_text()}")
            
            try:
                # Explicit wait for URL to change away from registration
                playwright_page.wait_for_url(lambda u: "/registration" not in u.split('?')[0] or "/idv/" in u, timeout=15000)
                logger.info("📡 Page transitioned successfully.")
            except:
                logger.warning("Timed out waiting for URL transition, checking for persistent buttons...")
                # If button is STILL there and visible, maybe it wasn't clicked?
                btn = playwright_page.locator("xpath=//*[@id='registrationSubmit']").first
                if _safe_is_visible(btn, timeout=1000):
                    logger.info("🖱️ Submit button still visible, attempting final forceful click...")
                    try: btn.click(force=True, timeout=1000)
                    except: pass
            
            for _ in range(10):
                time.sleep(1)
                new_state = detect_dev_state(playwright_page)
                if new_state != "registration_form":
                    logger.info(f"Transition Detected: {new_state}")
                    break

    return session.completion_flags["dev_registration"]
