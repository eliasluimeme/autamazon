"""
Popup and Passkey Blocker Utility (Active Sticky Injector)
Avoids add_init_script to prevent ERR_TUNNEL_CONNECTION_FAILED on proxy-connected browsers.
Uses event listeners to maintain the blocker across navigations and popups.
"""

from loguru import logger
import time

# JavaScript Payload to disable WebAuthn and window.open
BLOCKER_JS = """
    (function() {
        if (window.__automation_blocker_active) return;
        window.__automation_blocker_active = true;
        
        console.info('🛡️ Automation blocker active...');
        
        // 1. Disable WebAuthn completely
        if (window.PublicKeyCredential) {
            PublicKeyCredential.isUserVerifyingPlatformAuthenticatorAvailable = () => Promise.resolve(false);
            PublicKeyCredential.isConditionalMediationAvailable = () => Promise.resolve(false);
        }

        if (navigator.credentials) {
            const block = () => {
                console.log('🚫 navigator.credentials call blocked');
                return Promise.reject(new DOMException("Passkey Blocked by Automation", "NotAllowedError"));
            };
            navigator.credentials.create = block;
            navigator.credentials.get = block;
        }
        
        // 2. Prevent window.open from spawning zombie tabs
        const originalOpen = window.open;
        window.open = function() {
            console.log('🚫 window.open blocked by automation');
            return { 
                focus: () => {}, 
                close: () => {}, 
                closed: true, 
                location: { href: 'about:blank' } 
            };
        };
    })();
"""

def setup_robust_popup_blocker(page):
    """
    Sticky Active Blocker.
    Uses 'framenavigated' event to re-inject the blocker logic every time the page moves.
    This avoids broken proxy tunnels caused by add_init_script.
    """
    logger.info("🛡️ Initializing sticky active blocker (Tunnel-safe)")
    
    # Define the injection function
    def inject():
        try:
            # We use a non-blocking evaluate
            page.evaluate(BLOCKER_JS)
        except:
            pass

    # Initial injection
    inject()

    # Re-inject on every navigation to ensure persistence
    # 'framenavigated' is better than 'load' as it fires earlier
    try:
        page.on("framenavigated", lambda frame: inject() if frame == page.main_frame else None)
        page.on("domcontentloaded", lambda p: inject())
        
        # Recursive setup for any popup that might appear
        page.on("popup", lambda p: setup_robust_popup_blocker(p))
        
        logger.success("✅ Sticky blocker activated and recursive for popups")
    except Exception as e:
        logger.debug(f"Blocker event attachment failed (page might be closing): {e}")

def cleanup_blocker(page):
    """Note: Listeners stay active until page closes."""
    pass
