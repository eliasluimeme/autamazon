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
    Uses a multi-priority approach: ESC key -> Cached selectors -> AgentQL -> JS fallback.
    """
    if device is None:
        device = DeviceAdapter(page)
        
    url = page.url.lower()
    
    # 1. Broad detection (is_nudge_page)
    is_nudge_page = False
    if "/claim/webauthn/nudge" in url or "webauthn" in url:
        is_nudge_page = True
    
    indicators = [
        "text='Use face ID, fingerprint, or PIN to sign in'",
        "text='Set up a passkey'",
        "text='Create a passkey'",
        "text='Skip'",
        "#passkey-nudge-skip-button"
    ]
    
    if not is_nudge_page:
        for indicator in indicators:
            try:
                if page.locator(indicator).first.is_visible(timeout=500):
                    is_nudge_page = True
                    break
            except: continue
                
    if not is_nudge_page:
        return True # Not on nudge page, continue
        
    logger.info("🛡️ Passkey nudge detected. Dismissing popups and skipping...")
    
    # 2. Clear potential system popups (Touch ID / Fingerprint / WebAuthn)
    # This is critical as these dialogs block traditional Playwright clicks
    logger.info("⌨️ Dismissing browser/system passkey dialog (ESC x3)...")
    try:
        page.bring_to_front()
        for _ in range(3):
            page.keyboard.press("Escape")
            time.sleep(0.3)
    except Exception as e:
        logger.debug(f"Escape key failed: {e}")

    # 3. Priority 1: AgentQL / Cached selectors for pinpoint accuracy
    try:
        from amazon.agentql_helper import query_amazon
        results = query_amazon(page, "passkey_nudge")
        
        # Prioritize Cancel as requested by user / Outlook inspiration
        btn_data = results.get("cancel_link") or results.get("skip_button")
        
        if btn_data and btn_data.get('element'):
            element = btn_data['element']
            logger.info(f"Found {'Cancel' if results.get('cancel_link') else 'Skip'} button via AgentQL, clicking...")
            # Use js_click for maximum reliability as it bypasses overlays
            device.js_click(element, "passkey dismiss button (AgentQL)")
            time.sleep(random.uniform(*DELAYS["page_load"]))
            return True
    except Exception as e:
        logger.debug(f"AgentQL approach failed for passkey: {e}")

    # 4. Priority 2: Standard Selectors
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
        "#passkey-creation-skip-link"
    ]
    
    for selector in skip_selectors:
        try:
            element = page.locator(selector).first
            if element.is_visible(timeout=1000):
                logger.info(f"Found Skip button via selector: {selector}")
                device.js_click(element, f"Skip button ({selector})")
                time.sleep(random.uniform(*DELAYS["page_load"]))
                return True
        except: continue
            
    # 5. Priority 3: Ultimate JS Fallback (Text-based search)
    try:
        result = page.evaluate("""
            () => {
                const elements = Array.from(document.querySelectorAll('a, button, span, div'));
                const skipBtn = elements.find(el => {
                    if (!el.textContent) return false;
                    const t = el.textContent.toLowerCase().trim();
                    const targets = ['skip', 'not now', 'no, keep using', 'skip setup', 'maybe later'];
                    return targets.includes(t) || (t.includes('skip') && t.length < 15);
                });
                if (skipBtn) {
                    skipBtn.click();
                    ['mousedown', 'click', 'mouseup'].forEach(n => skipBtn.dispatchEvent(new MouseEvent(n, {bubbles:true})));
                    return true;
                }
                return false;
            }
        """)
        if result:
            logger.success("✓ Skip button clicked via ultimate JS fallback")
            time.sleep(random.uniform(*DELAYS["page_load"]))
            return True
    except: pass
            
    logger.warning("Could not click Skip button on passkey nudge. Continuing anyway...")
    return False
