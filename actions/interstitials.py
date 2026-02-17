"""
Common Amazon Interstitials Handler

Handles popups and overlays that block the main flow, 
particularly the "Select your address" or "Deliver to..." popup.
"""

import time
import random
from loguru import logger
from amazon.device_adapter import DeviceAdapter

def handle_address_interstitial(page, device: DeviceAdapter = None) -> bool:
    """
    Check for and dismiss the address selection popup.
    Usually appears on mobile or first-time desktop visits.
    """
    if device is None:
        device = DeviceAdapter(page)
        
    logger.debug("Checking for address interstitial...")
    
    try:
        # 1. "Deliver to..." popup (GLux)
        # Often has text like "Select your address" or "Deliver to..."
        dismiss_selectors = [
            "input[data-action-type='DISMISS']",
            "#GLUXConfirmClose",
            ".a-button-close",
            "button:has-text('Done')",
            "#GLUXZipUpdate-announce + span input", # The Submit button in Glux
            "#GLUXConfirmClose:visible",
            "input[type='submit'][aria-labelledby='GLUXZipUpdate-announce']",
            "span:has-text('Submit'):visible",
            "input[type='submit'][value='Submit']",
            "input[type='submit'][value='Done']",
            "#nav-global-location-slot span.a-button-inner input",
            ".glow-toaster-button-dismiss input",
        ]
        
        for selector in dismiss_selectors:
            try:
                btn = page.locator(selector).first
                if btn.is_visible(timeout=500):
                    logger.info(f"📍 Dismissing address popup with: {selector}")
                    btn.click()
                    time.sleep(1)
                    return True
            except:
                continue
                
        # 2. Check for the "Choose your location" overlay
        # Sometimes it's a "Continue" button or "Keep [Country]"
        try:
            continue_btn = page.locator("input[data-action-type='SELECT_LOCATION_AND_CONTINUE']").first
            if continue_btn.is_visible(timeout=500):
                logger.info("📍 Clicking Continue on location popup")
                continue_btn.click()
                time.sleep(1)
                return True
        except:
            pass
            
    except Exception as e:
        logger.debug(f"Address interstitial check error (non-fatal): {e}")
        
    return False

def handle_international_popup(page, device: DeviceAdapter = None) -> bool:
    """
    Handle the 'Stay on Amazon.com.au' vs 'Go to Amazon.com' popup.
    Usually wants to stay on the local site.
    """
    if device is None:
        device = DeviceAdapter(page)
        
    logger.debug("Checking for international store popup...")
    
    try:
        # 1. Look for the "Stay on [Local Site]" button
        # This is usually the preferred action for the local automation
        stay_selectors = [
            "input[type='submit'][value*='Stay on']",
            "button:has-text('Stay on')",
            "span:has-text('Stay on')",
            ".a-button-inner:has-text('Stay on') input",
            "input[value*='Keep shopping']",
        ]
        
        for selector in stay_selectors:
            try:
                btn = page.locator(selector).first
                if btn.is_visible(timeout=500):
                    logger.info(f"📍 Staying on local Amazon via: {selector}")
                    btn.click()
                    time.sleep(1)
                    return True
            except:
                continue
                
        # 2. Look for the close button (X) in the popover
        close_selectors = [
            ".a-popover-header .a-button-close",
            ".a-modal-header .a-button-close",
            "button[aria-label='Close']",
        ]
        
        for selector in close_selectors:
            try:
                btn = page.locator(selector).first
                if btn.is_visible(timeout=500):
                    logger.info(f"📍 Closing international popup via: {selector}")
                    btn.click()
                    time.sleep(1)
                    return True
            except:
                continue
                
    except Exception as e:
        logger.debug(f"International popup check error: {e}")
    
    return False

def handle_generic_popups(page, device: DeviceAdapter = None):
    """Handle multiple common popups in one go."""
    # handle_address_interstitial(page, device)
    # handle_international_popup(page, device)
    
    # Add other popups here if needed
    # Example: Cookies (for international sites)
    try:
        cookie_btn = page.locator("#sp-cc-accept").first
        if cookie_btn.is_visible(timeout=500):
            logger.info("📍 Accepting cookies...")
            cookie_btn.click()
    except:
        pass
