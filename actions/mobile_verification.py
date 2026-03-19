"""
Amazon Mobile Verification Handler

Handles the "Add mobile number" step in Amazon signup flow.
This is a 2-step process:
  1. Enter mobile number
  2. Verify with OTP sent to phone

This step is optional - not all signups require it.
"""

import time
import random
import re
from loguru import logger

from amazon.device_adapter import DeviceAdapter
from modules.onlinesim_handler import OnlineSimHandler
import config

# Mapping of OnlineSim country codes to ISO codes and names for Amazon
COUNTRY_CODE_MAP = {
    "1": "US",
    "61": "AU",
    "44": "GB",
    "33": "FR",
    "49": "DE",
    "7": "RU",
    "32": "BE",
    "31": "NL",
    "34": "ES",
    "39": "IT",
    "1": "CA", # Multiple countries share +1
}


def handle_add_mobile_step(page, phone_number: str = None, device: DeviceAdapter = None) -> bool:
    """
    Handle the Add Mobile Number step.
    If phone_number is provided AND automated verification is possible via OnlineSim,
    it will use OnlineSim. Otherwise fallbacks or skips.
    
    Args:
        page: Playwright page object
        phone_number: Optional phone number (if None, will rent one from OnlineSim)
        device: DeviceAdapter for human-like interactions
        
    Returns:
        True if handled successfully, False otherwise
    """
    if device is None:
        device = DeviceAdapter(page)
    
    logger.info("📱 Handling Add Mobile Number step...")
    
    # 1. Check if we have OnlineSim API key
    if config.ONLINESIM_API_KEY:
        logger.info("🤖 Automated OnlineSim verification available.")
        return handle_automated_mobile_verification(page, device)
    
    # 2. Manual/Static Fallback (Existing logic)
    # If no phone number provided, try to skip this step
    if not phone_number:
        logger.info("No phone number provided and no OnlineSim API, attempting to skip...")
        return _try_skip_mobile_step(page, device)
    
    # Step 1: Enter the phone number
    if not _enter_phone_number(page, phone_number, device):
        logger.warning("Failed to enter phone number")
        return _try_skip_mobile_step(page, device)
    
    # Step 2: Wait for and enter OTP (requires manual intervention or SMS API)
    logger.warning("📱 Phone OTP verification required - MANUAL INTERVENTION NEEDED")
    logger.warning("👉 Please check your phone for the OTP and enter it manually.")
    
    return _wait_for_mobile_verification(page)


def handle_automated_mobile_verification(page, device: DeviceAdapter, max_retries: int = None) -> bool:
    """
    Automated flow using OnlineSim API.
    """
    if max_retries is None:
        max_retries = config.ONLINESIM_RETRY_COUNT
        
    handler = OnlineSimHandler()
    
    for attempt in range(max_retries):
        logger.info(f"🔄 Automated Mobile Verification - Attempt {attempt + 1}/{max_retries}")
        
        # 1. Get a number (Try activation first, it's cheaper)
        tzid, number = handler.get_number(service="amazon")
        is_rent = False
        
        if not tzid:
            logger.info("Activation API failed, falling back to Rent API...")
            tzid, number = handler.rent_number()
            is_rent = True
            
        if not tzid or not number:
            logger.error("Failed to obtain a number from OnlineSim (both activation and rent failed).")
            break
            
        # 2. Enter the number
        if not _enter_phone_number(page, number, device):
            logger.warning(f"Could not enter number {number}. Closing and retrying...")
            handler.close_number(tzid, is_rent=is_rent)
            continue
            
        # 3. Check for immediate Amazon errors
        error_msg = _check_amazon_phone_error(page)
        if error_msg:
            logger.warning(f"❌ Amazon rejected number {number}: {error_msg}")
            handler.close_number(tzid, is_rent=is_rent)
            time.sleep(2)
            continue
            
        # 4. Wait for SMS
        otp_code, actual_number = handler.get_sms(tzid, is_rent=is_rent)
        if not otp_code:
            logger.warning(f"⏰ Did not receive SMS for {number}. Closing and retrying...")
            handler.close_number(tzid, is_rent=is_rent)
            continue
            
        # 5. Enter OTP code
        if _enter_otp_code(page, device, otp_code):
            logger.success(f"✅ Mobile verification successful with number {number}!")
            handler.close_number(tzid, is_rent=is_rent)
            return True
        else:
            logger.error(f"❌ Failed to submit OTP {otp_code} for {number}.")
            handler.close_number(tzid, is_rent=is_rent)
            # This might be due to invalid OTP or Amazon error after entry
            error_msg = _check_amazon_phone_error(page)
            if error_msg:
                logger.error(f"Amazon error after OTP: {error_msg}")
            
    logger.error("❌ Automated mobile verification failed after all retries.")
    return _try_skip_mobile_step(page, device)


def _check_amazon_phone_error(page) -> str | None:
    """Check for error messages on the Amazon phone/OTP entry page."""
    error_selectors = [
        ".a-alert-error",
        "#auth-error-message-box",
        ".cvf-widget-alert",
        "div[role='alert']",
        ".a-box-error"
    ]
    
    # Common error strings:
    # "This phone number is already in use."
    # "The mobile phone number you entered is invalid."
    # "Please enter a valid mobile phone number."
    # "Invalid OTP. Please check your phone for the verification code."
    
    for selector in error_selectors:
        try:
            loc = page.locator(selector).first
            if loc.is_visible(timeout=1000):
                text = loc.inner_text().strip()
                if text:
                    return text
        except:
            continue
            
    return None


def _enter_otp_code(page, device: DeviceAdapter, otp_code: str) -> bool:
    """Enter the OTP code for phone verification."""
    otp_selectors = [
        "input[name='cvf_phone_otp']",
        "input[name='code']",
        "#cvf-phone-otp-input",
        "input[type='text'][maxlength='6']",
        "input[aria-label*='Code']",
        "input[placeholder*='code']"
    ]
    
    for selector in otp_selectors:
        try:
            input_el = page.locator(selector).first
            if input_el.is_visible(timeout=2000):
                logger.info(f"Filling phone OTP with: {selector}")
                input_el.fill("")
                time.sleep(0.2)
                device.type_text(input_el, otp_code, "phone OTP")
                time.sleep(0.5)
                
                # Click verify button
                return _click_verify_otp_button(page, device)
        except:
            continue
            
    logger.error("Could not find OTP input field for phone verification")
    return False


def _click_verify_otp_button(page, device: DeviceAdapter) -> bool:
    """Click the button to verify phone OTP."""
    button_selectors = [
        "input[name='cvf_action_proceed']",
        "input[type='submit'][value='Verify']",
        "button:has-text('Verify')",
        "#cvf-submit-otp-button",
        "input[name='cvf_phone_num_verify']"
    ]
    
    for selector in button_selectors:
        try:
            btn = page.locator(selector).first
            if btn.is_visible(timeout=1000):
                logger.info(f"Clicking phone OTP verify button with: {selector}")
                device.scroll_to_element(btn, "Verify OTP button")
                time.sleep(0.4)
                btn.click()
                time.sleep(3)
                return True
        except:
            continue
            
    return False


def _try_skip_mobile_step(page, device: DeviceAdapter) -> bool:
    """Try to skip the mobile verification step if possible."""
    
    skip_selectors = [
        "a:has-text('Skip')",
        "button:has-text('Skip')",
        "a:has-text('Not now')",
        "button:has-text('Not now')",
        "a:has-text('skip')",
        ":has-text('Add later')",
        "a:has-text('I'll do it later')",
    ]
    
    for selector in skip_selectors:
        try:
            skip_btn = page.locator(selector).first
            if skip_btn.is_visible(timeout=500):
                logger.info(f"Found skip option with: {selector}")
                device.scroll_to_element(skip_btn, "Skip button")
                time.sleep(random.uniform(0.3, 0.6))
                skip_btn.click()
                time.sleep(2)
                return True
        except:
            continue
    
    logger.warning("⚠️ No skip option found for mobile verification")
    logger.warning("👉 MANUAL INTERVENTION REQUIRED - Please skip or complete mobile verification")
    
    # Wait for user to handle it manually
    return _wait_for_page_change(page, max_wait=120)


def _enter_phone_number(page, phone_number: str, device: DeviceAdapter) -> bool:
    """Enter the phone number in the input field."""
    
    # 1. Select the correct country code first
    target_country = str(config.ONLINESIM_DEFAULT_COUNTRY)
    _select_country_code(page, target_country, device)
    
    # Clean the phone number (remove prefix if it matches target_country)
    # OnlineSim numbers often include the prefix (e.g. 61412345678)
    clean_number = phone_number
    if clean_number.startswith(target_country):
        clean_number = clean_number[len(target_country):]
    elif clean_number.startswith("+" + target_country):
        clean_number = clean_number[len(target_country)+1:]
        
    # 2. Phone number input selectors
    phone_input_selectors = [
        "input[name='cvf_phone_num']",
        "input[type='tel']",
        "input[placeholder*='phone']",
        "input[placeholder*='mobile']",
        "#cvf-phone-num-input",
    ]
    
    for selector in phone_input_selectors:
        try:
            phone_input = page.locator(selector).first
            if phone_input.is_visible(timeout=500):
                logger.info(f"Found phone input with: {selector}")
                device.scroll_to_element(phone_input, "Phone input")
                time.sleep(random.uniform(0.2, 0.4))
                
                # Clear any existing value
                phone_input.fill("")
                time.sleep(0.2)
                
                # Type the cleaned phone number
                logger.info(f"Typing cleaned number: {clean_number}")
                device.type_text(phone_input, clean_number, "phone number")
                time.sleep(0.5)
                
                # Click the Add/Continue button
                return _click_add_mobile_button(page, device)
        except:
            continue
    
    logger.warning("Could not find phone number input field")
    return False


def _click_add_mobile_button(page, device: DeviceAdapter) -> bool:
    """Click the 'Add mobile number' button."""
    
    button_selectors = [
        "input[name='cvf_action_proceed']",
        "input[type='submit']",
        "button.cvf-widget-btn-verify",
        "button:has-text('Add mobile number')",
        "span:has-text('Add mobile number')",
        "#cvf-submit-btn",
    ]
    
    for selector in button_selectors:
        try:
            btn = page.locator(selector).first
            if btn.count() > 0:
                logger.info(f"Clicking Add Mobile button with: {selector}")
                # Try JS click first to avoid interception by popovers or overlays
                btn.evaluate("el => el.click()")
                time.sleep(3)
                return True
        except:
            continue
    
    return False


def _wait_for_mobile_verification(page, max_wait: int = 180) -> bool:
    """
    Wait for user to complete mobile OTP verification.
    
    Returns True if verification completes, False if timeout.
    """
    logger.info(f"⏳ Waiting up to {max_wait}s for mobile verification...")
    
    print("\n" + "=" * 60)
    print("   >>>  PLEASE VERIFY YOUR PHONE NUMBER  <<<")
    print("   (Enter the OTP sent to your phone)")
    print("=" * 60 + "\n")
    
    start_time = time.time()
    initial_url = page.url
    
    while time.time() - start_time < max_wait:
        elapsed = int(time.time() - start_time)
        
        # Check if URL changed (moved to next step)
        current_url = page.url
        if current_url != initial_url:
            # Check if we're no longer on mobile verification
            if "/ap/cvf/verify" not in current_url.lower():
                logger.info("✅ Mobile verification completed (URL changed)")
                return True
        
        # Check for success indicators
        try:
            if page.locator(":has-text('Verification successful')").first.is_visible(timeout=300):
                logger.info("✅ Mobile verification successful")
                return True
        except:
            pass
        
        # Check if mobile step is gone
        try:
            if not page.locator(":has-text('Add mobile number')").first.is_visible(timeout=300):
                if not page.locator(":has-text('Verify mobile')").first.is_visible(timeout=300):
                    logger.info("✅ Mobile step no longer visible")
                    return True
        except:
            pass
        
        # Log progress every 30 seconds
        if elapsed > 0 and elapsed % 30 == 0:
            logger.info(f"⏳ Still waiting for mobile verification... ({elapsed}s elapsed)")
        
        time.sleep(2)
    
    logger.error(f"❌ Mobile verification timed out after {max_wait}s")
    return False


def _wait_for_page_change(page, max_wait: int = 120) -> bool:
    """Wait for the page to change (URL or content)."""
    
    start_time = time.time()
    initial_url = page.url
    
    while time.time() - start_time < max_wait:
        if page.url != initial_url:
            logger.info("Page changed, mobile step handled")
            return True
        
        elapsed = int(time.time() - start_time)
        if elapsed > 0 and elapsed % 30 == 0:
            logger.info(f"⏳ Waiting for page change... ({elapsed}s)")
        
        time.sleep(2)
    
    return False


def _select_country_code(page, country_code: str, device: DeviceAdapter) -> bool:
    """
    Select the country code in Amazon's dropdown.
    country_code: e.g. "61" or "1"
    """
    try:
        # 1. Check if dropdown is already open (look for the popover)
        popover_selector = ".a-popover.a-dropdown, #a-popover-1"
        is_open = page.locator(popover_selector).first.is_visible(timeout=500)
        
        if not is_open:
            # Open the dropdown
            # Use a more specific selector for the button itself if possible
            dropdown_selectors = [
                '#cvf_phone_cc_aui',
                '//*[@id="cvf_phone_cc_aui"]/span/span',
                '.a-dropdown-container span[data-action="a-dropdown-button"]'
            ]
            
            opened = False
            for sel in dropdown_selectors:
                try:
                    btn = page.locator(sel).first
                    if btn.is_visible(timeout=1000):
                        logger.info(f"Opening country code dropdown via {sel}...")
                        # Try JS click to avoid interception
                        btn.evaluate("el => el.click()")
                        time.sleep(1)
                        if page.locator(popover_selector).first.is_visible(timeout=2000):
                            opened = True
                            break
                except:
                    continue
            
            if not opened:
                logger.warning("Could not open country code dropdown")
                return False
        else:
            logger.info("Country code dropdown already open")
            
        # 2. Find and click the target country
        iso_code = COUNTRY_CODE_MAP.get(str(country_code))
        
        # Strategy A: Data-value ISO match
        if iso_code:
            # We use a simpler selector to avoid syntax errors with nested quotes
            # Look for li with class cvf-country-code-option where inner a has data-value containing ISO
            iso_selectors = [
                f'#cvf_phone_cc_native_11', # Direct ID if AU
                f'li.cvf-country-code-option:has([data-value*="{iso_code}"])',
                f'li:has([data-value*="{iso_code}"])',
                f'.a-dropdown-item:has([data-value*="{iso_code}"])'
            ]
            
            for sel in iso_selectors:
                option = page.locator(sel).first
                if option.count() > 0:
                    logger.info(f"Selecting country {iso_code} via {sel}")
                    # Use JS click as it's more reliable in popovers
                    option.evaluate("el => el.click()")
                    time.sleep(1)
                    return True
                
        # Strategy B: Search by text containing +prefix
        prefix = f"+{country_code}"
        text_selectors = [
            f"li:has-text('{prefix}')",
            f"a:has-text('{prefix}')",
            f"span:has-text('{prefix}')",
            f"role=option >> text='+{country_code}'"
        ]
        
        for sel in text_selectors:
            # Make sure we only click within the dropdown items
            option = page.locator(f".a-popover {sel}, .cvf-country-code-option {sel}, .a-dropdown-item {sel}").first
            if option.count() > 0:
                logger.info(f"Selecting country via prefix {prefix} using {sel}")
                option.evaluate("el => el.click()")
                time.sleep(1)
                return True
                
        logger.warning(f"Could not find country option for {country_code}")
        # Close the dropdown if still open
        page.keyboard.press("Escape")
        return False
        
    except Exception as e:
        logger.warning(f"Error selecting country code: {e}")
        return False


def is_add_mobile_page(page) -> bool:
    """Check if current page is the Add Mobile Number page."""
    
    url = page.url.lower()
    
    # URL check
    if "/ap/cvf/verify" in url:
        return True
    
    # Content check
    indicators = [
        ":has-text('Add mobile number')",
        ":has-text('Step 1 of 2')",
        ":has-text('New mobile number')",
    ]
    
    for indicator in indicators:
        try:
            if page.locator(indicator).first.is_visible(timeout=300):
                return True
        except:
            pass
    
    return False
