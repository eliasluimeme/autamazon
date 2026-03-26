"""
Popup and Passkey Blocker Utility (Active Injector)
Avoids pre-navigation hooks entirely to protect proxy tunnels.
"""

from loguru import logger

def setup_robust_popup_blocker(page):
    """
    Experimental Lazy Blocker. 
    Does NOT use init scripts (which can break proxy handshakes in AdsPower).
    Instead, it injects JS actively into the current DOM.
    """
    logger.info("🛡️ Setting up active blocker (Safe for proxies)")
    
    # We DO NOT use add_init_script here to avoid interfering with tunnel setup
    inject_safe_blocker_js(page)

def inject_safe_blocker_js(page):
    """Actively injects the blocker into the currently running page."""
    try:
        page.evaluate("""
            (function() {
                // 1. Block Passkey/WebAuthn APIs
                if (navigator.credentials) {
                    const block = () => Promise.reject(new DOMException("Passkey Blocked", "NotAllowedError"));
                    navigator.credentials.create = block;
                    navigator.credentials.get = block;
                    console.log('🛡️ Passkey blocker actively injected');
                }
                
                // 2. Prevent window.open from spawning zombie tabs
                window.open = function() {
                    console.log('🚫 window.open blocked by automation');
                    return { focus: () => {}, close: () => {}, closed: true };
                };
            })();
        """)
        
        # 3. Setup tab closer AFTER initial tunnel is established
        # We handle this via a lazy listener
        # page.on("popup", lambda p: p.close() if not p.is_closed() else None)
        
    except Exception as e:
        logger.debug(f"Active injection failed (non-critical, page might be loading): {e}")

def cleanup_blocker(page):
    pass
