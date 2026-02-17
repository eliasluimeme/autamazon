"""
Passkey Nudge Handler for Amazon Automation

Handles the "Use face ID, fingerprint, or PIN to sign in" nudge page:
- Clears system popups via Escape key
- Clicks "Skip" to continue
"""

import time
import random
from loguru import logger

from amazon.config import DELAYS
from amazon.device_adapter import DeviceAdapter

def handle_passkey_nudge(page, device: DeviceAdapter = None) -> bool:
    """
    Detect and skip the Amazon passkey setup nudge.
    
    Args:
        page: Playwright page object
        device: DeviceAdapter instance
        
    Returns:
        True if skipped or not present
    """
    if device is None:
        device = DeviceAdapter(page)
        
    url = page.url.lower()
    
    # Check if we're on the passkey nudge page
    is_nudge_page = False
    if "/claim/webauthn/nudge" in url or "webauthn" in url:
        is_nudge_page = True
    
    # Content indicators
    indicators = [
        "text='Use face ID, fingerprint, or PIN to sign in'",
        "text='Use your face, fingerprint, or PIN'",
        "text='Set up a passkey'",
        "text='Create a passkey'",
        "text='Skip the password next time'", # From two_step_verification
        "#passkey-nudge-skip-button",
        "text='Not now'",
        "text='Skip'"
    ]
    
    if not is_nudge_page:
        for indicator in indicators[:2]:
            try:
                if page.locator(indicator).first.is_visible(timeout=1000):
                    is_nudge_page = True
                    break
            except:
                continue
                
    if not is_nudge_page:
        return True # Not on nudge page, continue
        
    logger.info("🛡️ Passkey nudge detected, skipping...")
    
    # 1. Clear potential system popups (Touch ID / Fingerprint)
    # The user suggested clicking Esc 3 times
    logger.info("Sending Escape x3 to clear system popups...")
    for _ in range(3):
        page.keyboard.press("Escape")
        time.sleep(0.5)
        
    # 2. Click "Skip" button
    skip_selectors = [
        "#passkey-nudge-skip-button",
        "button:has-text('Skip setup')",
        "a:has-text('Skip setup')",
        "a:has-text('Skip')",
        "button:has-text('Skip')",
        "text='Skip'",
        ".a-button-text:has-text('Skip')",
        "a:has-text('Not now')",
        "button:has-text('Not now')",
        "text='Not now'",
        ".a-button-text:has-text('Not now')",
        "#passkey-creation-skip-link",
        "text='No, keep using password'" # From two_step_verification
    ]
    
    clicked = False
    for selector in skip_selectors:
        try:
            element = page.locator(selector).first
            if element.is_visible(timeout=2000):
                logger.info(f"Found Skip button with selector: {selector}")
                device.tap(element, "Skip button")
                clicked = True
                break
        except:
            continue
            
    if not clicked:
        # Try JS fallback for Skip
        try:
            result = page.evaluate("""
                () => {
                    const elements = document.querySelectorAll('a, button, span, div');
                    for (const el of elements) {
                        if (el.textContent && el.textContent.trim() === 'Skip') {
                            el.click();
                            return 'clicked_text';
                        }
                    }
                    return null;
                }
            """)
            if result:
                logger.success(f"✓ Skip button clicked via JS: {result}")
                clicked = True
        except:
            pass
            
    if clicked:
        time.sleep(random.uniform(*DELAYS["page_load"]))
        return True
        
    logger.warning("Could not click Skip button on passkey nudge")
    return False
