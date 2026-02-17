import time
import random
from loguru import logger
from amazon.device_adapter import DeviceAdapter
from amazon.agentql_helper import query_amazon

REGISTRATION_URL = "https://developer.amazon.com/settings/console/registration?return_to=/settings/console/home"

def navigate_to_developer_registration(page):
    """Navigate to the developer registration page."""
    logger.info(f"🌐 Navigating to developer registration: {REGISTRATION_URL}")
    page.goto(REGISTRATION_URL, wait_until="load", timeout=60000)
    time.sleep(2)

def fill_developer_registration_form(page, identity, device: DeviceAdapter, aql_page=None):
    """Fills the developer registration form with proper dropdown handling."""
    logger.info("📝 Filling developer registration form...")
    
    # Wait for page to stabilize
    time.sleep(2)
    
    filled_fields = []
    
    # Map country names to abbreviations for phone prefix
    country_abbrev_map = {
        "United States": "US",
        "Australia": "AU",
        "United Kingdom": "GB",
        "Canada": "CA",
        "Germany": "DE",
        "France": "FR",
        "Spain": "ES",
        "Italy": "IT",
        "Netherlands": "NL",
        "Brazil": "BR",
        "Mexico": "MX",
        "Japan": "JP",
        "India": "IN",
    }
    country_abbrev = country_abbrev_map.get(identity.country, "US")
    
    # ===== 1. Country Selection (React Styled Dropdown) =====
    logger.info(f"Filling Country: {identity.country}...")
    country_selected = False
    try:
        # Use specific country input selector: #country_code
        # User Feedback: "after clicking the input dont wait, type the country and click on the first option."
        country_input = page.locator("#country_code").first
        
        if country_input.is_visible(timeout=3000):
            # 1. Click to open (Fire and forget style)
            try:
                # Use very short timeout. If it acts up, we assume it's open/focused or we use JS next.
                country_input.click(timeout=1000, force=True)
            except:
                # If click times out, it might be stuck waiting for animation, but input might be focused.
                # Just ensure focus with JS and move on.
                logger.debug("Click timed out, forcing focus via JS and proceeding...")
                try: 
                    page.evaluate("document.querySelector('#country_code').focus()")
                except: pass
            
            # 2. Type immediately (Don't wait)
            try:
                # Force fill/type
                country_input.fill("") 
                country_input.type(identity.country, delay=30)
            except:
                # Fallback to global keyboard if element interaction fails
                page.keyboard.type(identity.country, delay=30)
            
            time.sleep(0.5) # Wait for dropdown logic
            
            # 3. Click first option
            dropdown_option_selectors = [
                # User-provided XPath
                "xpath=//*[@id='root']/div/div[2]/div[2]/div[3]/div/div[3]/div/div/div[2]/div/div[1]/div[1]",
                # User-provided CSS selector (simplified)
                ".sc-caSCKo .sc-eqIVtm",
                # Fallback: first option in any dropdown
                "[role='option']:first-child",
                "div[class*='flinDQ'] > div:first-child > div",
            ]
            
            for sel in dropdown_option_selectors:
                try:
                    option = page.locator(sel).first
                    if option.is_visible(timeout=2000):
                        # Force click with short timeout to avoid waiting if dropdown disappears
                        try:
                            option.click(force=True, timeout=1000) 
                        except:
                            pass # Assume click worked if element disappeared
                        
                        filled_fields.append("country")
                        country_selected = True
                        logger.info(f"✓ Country selected: {identity.country}")
                        break
                except:
                    continue
        
        # Wait for form to potentially update/reload after country selection
        time.sleep(1)
                    
    except Exception as e:
        logger.warning(f"Error selecting country: {e}")

    # ===== 2. Text Input Fields (Sequential & Explicit) =====
    # User provided specific IDs/XPaths. We fill them in order.
    logger.info("Filling text fields...")
    
    fields_to_fill = [
        # (name, selector, value)
        ("Customer facing business name", "#company_name", identity.full_name),
        ("Address line 1", "#address_line", identity.address_line1),
        ("City", "#city", identity.city),
        ("Postal code", "#postal_code", identity.zip_code),
        ("State", "#state", identity.state),
    ]

    for name, selector, value in fields_to_fill:
        try:
            # Try ID first, then fallback to xpath if needed (though ID should work)
            field = page.locator(selector).first
            if not field.is_visible(timeout=2000):
                # Fallback to xpath based on ID if simple selector fails
                xpath = f"//*[@id='{selector.replace('#', '')}']"
                field = page.locator(f"xpath={xpath}").first
            
            if field.is_visible(timeout=2000):
                # Fire and forget click (don't wait for event)
                try:
                    field.click(force=True, timeout=1000)
                except:
                    pass # Proceed to type even if click times out
                
                # Check visibility again just in case, then type
                field.fill("")
                # Type with small delay to ensure it registers
                field.type(str(value), delay=20)
                filled_fields.append(name)
                logger.info(f"✓ Filled {name}")
            else:
                logger.warning(f"⚠️ Could not find field: {name} ({selector})")
        except Exception as e:
            logger.error(f"Error filling {name}: {e}")

    # ===== 3. Checkbox: Same as primary email =====
    try:
        # User feedback: click on label
        checkbox_selector = "#root > div > div.sc-cSHVUG.gEudZe.sc-iujRgT.jrEifw > div.sc-cSHVUG.gEudZe.sc-kpOJdX.czKwHF.sc-VJcYb.kcqpRp > div.sc-cooIXK.eYqdWn > div > label"
        checkbox = page.locator(checkbox_selector).first
        if not checkbox.is_visible(timeout=2000):
             checkbox = page.locator("xpath=//*[@id='root']/div/div[2]/div[4]/div[6]/div/label").first
             
        if checkbox.is_visible(timeout=2000):
            # Fire and forget click for checkbox/label
            try:
                checkbox.click(force=True, timeout=1000)
                logger.info("✓ Clicked 'Same as primary email'")
            except: 
                pass
    except Exception as e:
        logger.warning(f"Error clicking checkbox: {e}")

    # ===== 4. Phone Prefix Dropdown (Preserved) =====
    try:
        phone_prefix_selected = False
        
        # User-provided selector for phone prefix input: #phonemenu > input
        phone_prefix_input = page.locator("#phonemenu > input").first
        if not phone_prefix_input.is_visible(timeout=2000):
             # Try XPath fallback
             phone_prefix_input = page.locator("xpath=//*[@id='phonemenu']/input").first
        
        if phone_prefix_input.is_visible(timeout=2000):
            # 1. Click to open (Fire and forget style)
            try:
                phone_prefix_input.click(timeout=1000, force=True)
            except:
                logger.debug("Phone prefix click timed out, trying JS click...")
                page.evaluate("""
                    const el = document.querySelector('#phonemenu > input') || document.evaluate("//*[@id='phonemenu']/input", document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue;
                    if (el) el.click();
                """)
            
            # 2. Type immediately
            try:
                phone_prefix_input.fill("")
                phone_prefix_input.type(country_abbrev, delay=40)
            except:
                logger.debug("Phone prefix type failed, using keyboard...")
                phone_prefix_input.click(force=True)
                page.keyboard.type(country_abbrev, delay=40)
                
            time.sleep(0.5)
            
            # 3. Click first option
            phone_option_selectors = [
                "xpath=//*[@id='root']/div/div[2]/div[4]/div[7]/div/div[3]/div/div[1]/div[2]/div/div[1]/div[1]",
                ".sc-caSCKo .sc-eqIVtm",
                "[role='option']:first-child",
                "div[class*='flinDQ'] > div:first-child > div",
            ]
            
            for sel in phone_option_selectors:
                try:
                    option = page.locator(sel).first
                    if option.is_visible(timeout=2000):
                         # Force click with short timeout
                        try:
                            option.click(force=True, timeout=1000)
                        except:
                            pass
                        phone_prefix_selected = True
                        logger.info(f"✓ Phone prefix selected: {country_abbrev}")
                        break
                except:
                    continue
                    
    except Exception as e:
        logger.debug(f"Phone prefix error: {e}")

    # ===== 5. Phone Number Field =====
    try:
        phone_selector = "#company_phone"
        phone_input = page.locator(phone_selector).first
        if not phone_input.is_visible(timeout=2000):
            phone_input = page.locator("xpath=//*[@id='company_phone']").first
        
        if phone_input.is_visible(timeout=2000):
            current = phone_input.input_value()
            if current != identity.phone:
                # Fire and forget click
                try:
                    phone_input.click(force=True, timeout=1000)
                except:
                    pass
                
                phone_input.fill("")
                phone_input.type(identity.phone, delay=30)
                filled_fields.append("phone")
                logger.info("✓ Filled phone")
        else:
            logger.warning("⚠️ Phone input field not found")
    except Exception as e:
        logger.debug(f"Phone input error: {e}")

    # ===== 6. Submit Button =====
    time.sleep(0.5)
    submit_selector = "#registrationSubmit"
    
    form_submitted = False
    try:
        btn = page.locator(submit_selector).first
        if not btn.is_visible(timeout=1000):
             btn = page.locator("xpath=//*[@id='registrationSubmit']").first
             
        if btn.is_visible(timeout=2000):
            # Use force click to avoid "element is not stable" or scrolling issues
            try:
                btn.click(force=True)
            except:
                pass
            form_submitted = True
            logger.success("✓ Developer registration form submitted!")
    except Exception as e:
         logger.error(f"Error submitting form: {e}")
    
    return form_submitted

def handle_2step_verification_prompt(page):
    """Handles the 2-step verification prompt (QR code)."""
    try:
        if page.locator("text='Enroll a 2-Step Verification authenticator'").first.is_visible(timeout=5000) or \
           page.locator("text='Use an authenticator app'").first.is_visible(timeout=5000):
            
            logger.warning("🔒 [ACTION REQUIRED] Amazon Developer Registration requires 2-Step Verification (QR Code)!")
            print("\n" + "!"*60)
            print("!!! 2-STEP VERIFICATION REQUIRED - PLEASE SCAN QR CODE !!!")
            print("!!! AFTER ENROLLING, COMPLETE THE VERIFICATION IN THE BROWSER !!!")
            print("!"*60 + "\n")
            
            # Wait for user
            max_wait = 600 # 10 minutes
            start_time = time.time()
            while time.time() - start_time < max_wait:
                time.sleep(10)
                # Check if we moved past this page
                if not page.locator("text='Enroll a 2-Step Verification authenticator'").first.is_visible(timeout=1000):
                    logger.success("✓ 2-Step Verification completed manually")
                    return True
            
            logger.error("❌ 2-Step Verification timed out")
            return False
    except:
        pass
    return True
