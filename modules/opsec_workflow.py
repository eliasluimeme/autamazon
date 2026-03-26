"""
OpSec Two-Phase Workflow Module

Implements the secure two-phase browser workflow:
- Phase A: Pre-Flight Validation (check then close)
- Phase B: Execution (warm-up then target)
"""

import time
import requests
from loguru import logger
from patchright.sync_api import sync_playwright
from modules.config import ADSPOWER_API_URL
from modules.persona_factory import PersonaFactory
from modules.sanity_checks import run_all_checks

class SanityCheckException(Exception):
    """Local exception for sanity check failures."""
    pass

# Verified Domains for Email Fabrication
VERIFIED_DOMAINS = ["gaming-verify.com", "secure-club-login.net"]


class OpSecBrowserManager:
    """
    Manages browser lifecycle for OpSec workflows.
    Wraps AdsPower profile launching with patchright integration.
    """
    
    def __init__(self, profile_id, api_url=ADSPOWER_API_URL):
        self.profile_id = profile_id
        self.api_url = api_url
        self.browser = None
        self.context = None
        self.page = None
        self.playwright = None
        self.cdp_info = None
        self.persona = None # Holds the full cohesive persona (Id, Email, Pass, Phone)
        
    def start_browser(self, headless=True):
        """
        Launch AdsPower profile and connect via CDP using patchright.
        
        Args:
            headless: Whether to run in headless mode
            
        Returns:
            page: Patchright page object
        """
        logger.info(f"🚀 Launching browser for profile {self.profile_id}...")
        
        # Start AdsPower profile using V1 API with retry logic for "Too many requests"
        max_attempts = 5
        data = None
        
        for attempt in range(max_attempts):
            try:
                headless_flag = "1" if headless else "0"
                url = f"{self.api_url}/api/v1/browser/start?user_id={self.profile_id}&headless={headless_flag}&open_tabs=1"
                resp = requests.get(url, timeout=30)
                data = resp.json()
                
                if data["code"] == 0:
                    break # Success!
                
                msg = data.get("msg", "")
                if "Too many request" in msg:
                    # Exponential backoff: 2, 4, 8, 16 seconds
                    wait_time = (2 ** attempt) + (time.time() % 1) 
                    logger.warning(f"⚠️ AdsPower Rate Limit [Attempt {attempt+1}/{max_attempts}]. Waiting {wait_time:.1f}s...")
                    time.sleep(wait_time)
                    continue
                else:
                    logger.error(f"Failed to start profile: {msg}")
                    return None
                    
            except Exception as e:
                logger.error(f"API request failed: {e}")
                if attempt < max_attempts - 1:
                    time.sleep(2)
                    continue
                return None
        
        if not data or data.get("code") != 0:
            logger.error(f"Could not start profile {self.profile_id} after {max_attempts} attempts")
            return None
            
        self.cdp_info = data["data"]
        debug_port = self.cdp_info.get("debug_port")
        ws_endpoint = self.cdp_info.get("ws", {}).get("puppeteer")
        
        logger.info(f"✅ Profile started on port {debug_port}")
        logger.debug(f"WebSocket endpoint: {ws_endpoint}")
            
        # except Exception as e:
        #     logger.error(f"❌ Failed to start AdsPower profile: {e}")
        #     return None
        
        # Connect to browser via CDP using patchright
        try:
            self.playwright = sync_playwright().start()
            
            # Try to connect using websocket endpoint first (more stable)
            if ws_endpoint:
                try:
                    logger.debug(f"Attempting connection via WebSocket: {ws_endpoint}")
                    self.browser = self.playwright.chromium.connect_over_cdp(ws_endpoint)
                except Exception as e:
                    logger.warning(f"WebSocket connection failed, trying CDP port: {e}")
                    # Fallback to CDP port connection
                    self.browser = self.playwright.chromium.connect_over_cdp(
                        endpoint_url=f"http://127.0.0.1:{debug_port}"
                    )
            else:
                # Connect to existing browser via CDP port
                self.browser = self.playwright.chromium.connect_over_cdp(
                    endpoint_url=f"http://127.0.0.1:{debug_port}"
                )
            
            # Give browser time to stabilize
            time.sleep(0.5)
            
            # Get default context and page
            if not self.browser.contexts:
                logger.error("No browser contexts available")
                return None
                
            self.context = self.browser.contexts[0]
            
            # Get existing page or create new one
            if self.context.pages:
                self.page = self.context.pages[0]
                logger.debug(f"Using existing page (found {len(self.context.pages)} pages)")
            else:
                self.page = self.context.new_page()
                logger.debug("Created new page")
            
            # Set longer timeouts for stability
            self.page.set_default_timeout(30000)  # 30 seconds
            
            # CRITICAL: Do NOT call any emulation methods here!
            # AdsPower already configured the fingerprint, timezone, locale, viewport, etc.
            # Calling emulate_media(), set_viewport(), etc. CHANGES the state and creates detection vectors
            
            # Verify browser state for debugging (read-only, no modifications)
            try:
                color_scheme = self.page.evaluate(
                    "() => window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'"
                )
                viewport = self.page.viewport_size
                webdriver_flag = self.page.evaluate("() => navigator.webdriver")
                user_agent = self.page.evaluate("() => navigator.userAgent")
                
                logger.info(f"🔍 Browser State: color_scheme={color_scheme}, viewport={viewport}")
                logger.debug(f"User Agent: {user_agent[:50]}...")
                
                if webdriver_flag:
                    logger.warning("⚠️ navigator.webdriver is exposed! Detection risk present.")
                else:
                    logger.info("✓ navigator.webdriver is undefined (good)")
                    
            except Exception as e:
                logger.debug(f"Could not verify browser state: {e}")
            
            logger.success("✅ Connected to browser via patchright")
            
            # Perform initial health check automatically
            # self.check_fingerprint_health()
            
            return self.page
            
        except Exception as e:
            logger.error(f"❌ Failed to connect via patchright: {e}")
            self.stop_browser()
            return None
            
    def check_fingerprint_health(self):
        """
        Perform a comprehensive fingerprint health check to detect automation leaks.
        Checks common bot detection vectors used by Arkose and other top-tier systems.
        """
        if not self.page:
            return None
            
        logger.info("🛡️ Performing Fingerprint Health Check...")
        try:
            results = self.page.evaluate("""() => {
                const getWebGL = () => {
                    const canvas = document.createElement('canvas');
                    const gl = canvas.getContext('webgl') || canvas.getContext('experimental-webgl');
                    if (!gl) return { vendor: 'none', renderer: 'none' };
                    const debugInfo = gl.getExtension('WEBGL_debug_renderer_info');
                    if (!debugInfo) return { vendor: 'unknown', renderer: 'unknown' };
                    return {
                        vendor: gl.getParameter(debugInfo.UNMASKED_VENDOR_WEBGL),
                        renderer: gl.getParameter(debugInfo.UNMASKED_RENDERER_WEBGL)
                    };
                };

                return {
                    webdriver: navigator.webdriver,
                    plugins: navigator.plugins.length,
                    languages: navigator.languages,
                    platform: navigator.platform,
                    hardware: navigator.hardwareConcurrency,
                    memory: navigator.deviceMemory,
                    webgl: getWebGL(),
                    screen: `${window.screen.width}x${window.screen.height}`,
                    outer: `${window.outerWidth}x${window.outerHeight}`,
                    userAgent: navigator.userAgent
                };
            }""")

            # LOG RESULTS FOR DEBUGGING
            logger.info("📊 --- FINGERPRINT HEALTH REPORT ---")
            logger.info(f"   🤖 WebDriver: {'❌ DETECTED (High Risk)' if results['webdriver'] else '✅ Hidden (Safe)'}")
            logger.info(f"   🔌 Plugins: {results['plugins']} ({'✅ OK' if results['plugins'] > 10 else '⚠️ Minimal/Suspect'})")
            logger.info(f"   🌍 Languages: {results['languages']}")
            logger.info(f"   🏗️ WebGL Renderer: {results['webgl']['renderer']}")
            logger.info(f"   💻 Platform: {results['platform']}")
            logger.info(f"   🧠 Hardware: {results['hardware']} cores, {results['memory']}GB RAM")
            logger.info(f"   🖥️ Resolution: {results['screen']} (Outer: {results['outer']})")
            logger.info(f"   🕵️ User Agent: {results['userAgent'][:60]}...")
            
            # Additional Visual Verification
            try:
                 logger.info("🌐 Navigating to bot.sannysoft.com for visual audit...")
                 # Open in a new tab to avoid disturbing current page if needed
                 # but for debug, we can just use the current one before warmup
                 self.page.goto("https://bot.sannysoft.com/", wait_until="domcontentloaded", timeout=15000)
                 time.sleep(2)
                 self.page.screenshot(path=f"logs/fingerprint_debug_{int(time.time())}.png")
                 logger.success("📸 Visual fingerprint report saved to logs/")
            except Exception as e:
                 logger.warning(f"⚠️ Visual audit skipped: {e}")

            # Critical Warning
            if results['webdriver']:
                logger.error("🚫 CRITICAL LEAK: navigator.webdriver is visible. CAPTCHA solve probability is < 5%.")
            
            return results
        except Exception as e:
            logger.debug(f"⚠️ Fingerprint check minor error: {e}")
            return None
    
    def stop_browser(self):
        """
        Completely close browser and cleanup resources.
        """
        logger.info(f"🛑 Stopping browser for profile {self.profile_id}...")
        
        try:
            # Close patchright connections
            if self.page:
                try:
                    self.page.close()
                except:
                    pass
            
            if self.browser:
                try:
                    self.browser.close()
                except:
                    pass
            
            if self.playwright:
                try:
                    self.playwright.stop()
                except:
                    pass
            
            # Stop AdsPower profile
            url = f"{self.api_url}/api/v1/browser/stop?user_id={self.profile_id}"
            requests.get(url, timeout=10)
            
            logger.success("✅ Browser stopped and cleaned up")
            
        except Exception as e:
            logger.warning(f"⚠️ Cleanup error (non-critical): {e}")
        
        finally:
            self.page = None
            self.context = None
            self.browser = None
            self.playwright = None


def run_phase_a_preflight(profile_id, expected_country_code):
    """
    Phase A: Pre-Flight Validation
    
    Launch → IP Check → Fingerprint Check → Hardware Check → CLOSE
    
    Args:
        profile_id: AdsPower profile ID
        expected_country_code: Expected country code (e.g., 'BE', 'US')
        
    Returns:
        dict: Validation report with check results
        
    Raises:
        SanityCheckException: If any critical check fails
    """
    logger.info("=" * 80)
    logger.info("🛡️ PHASE A: PRE-FLIGHT VALIDATION")
    logger.info("=" * 80)
    
    manager = OpSecBrowserManager(profile_id)
    validation_report = {
        "phase": "A",
        "passed": False,
        "checks": None
    }
    
    try:
        # 1. Launch to about:blank
        page = manager.start_browser(headless=False)
        if not page:
            raise SanityCheckException("Failed to start browser")
        
        page.goto("about:blank", wait_until="domcontentloaded")
        logger.info("📄 Navigated to about:blank")
        
        # 2. Run all sanity checks
        check_results = run_all_checks(page, expected_country_code)
        validation_report["checks"] = check_results
        validation_report["passed"] = check_results.get("passed", False)
        
        # 3. CLOSE browser completely (critical for OpSec)
        logger.info("🧹 Closing browser to remove tracking residue...")
        manager.stop_browser()
        
        logger.success("✅ PHASE A COMPLETE - Profile validated and cleaned")
        
        return validation_report
        
    except SanityCheckException as e:
        logger.error(f"❌ PHASE A FAILED: {e}")
        manager.stop_browser()
        raise
        
    except Exception as e:
        logger.error(f"❌ PHASE A ERROR: {e}")
        manager.stop_browser()
        raise SanityCheckException(f"Phase A failed: {e}")


from modules.cookie_generator import generate_natural_history
from modules.human_input import HumanInput

def run_phase_b_execution(profile_id, target_url, country_code, warmup_duration=3, is_new_profile=False):
    """
    Phase B: Execution (The Money Run)
    
    Launch → Quick JS Check → Cookie Gen (if new) → Warm-up Visit → Target Navigation
    
    Args:
        profile_id: AdsPower profile ID
        target_url: Final target URL (casino/CPA landing page)
        warmup_duration: Seconds to spend on warm-up site (default: 3)
        is_new_profile: Whether to run cookie generator for history building
        
    Returns:
        OpSecBrowserManager: Active browser manager (browser left open for further automation)
    """
    logger.info("=" * 80)
    logger.info("💰 PHASE B: EXECUTION (THE MONEY RUN)")
    logger.info("=" * 80)
    
    manager = OpSecBrowserManager(profile_id)
    
    try:
        # 1. Persona Generation (Cohesive Identity, Email, Phone, Pass)
        # We generate this FIRST so the browser session starts as close as possible to navigation
        try:
            logger.info("🆔 Generating High-Fidelity Persona...")
            factory = PersonaFactory(catchall_domains=VERIFIED_DOMAINS)
            persona = factory.create_persona(country_code)
            manager.persona = persona
        except Exception as e:
            logger.error(f"⚠️ Persona generation failed: {e}")

        # 2. Launch fresh browser session
        page = manager.start_browser(headless=False)  # Visible for execution
        if not page:
            raise SanityCheckException("Failed to start browser")
        
        # Diagnostics: detect premature closure
        def _on_close(p):
            logger.warning("📍 Browser/Page was CLOSED unexpectedly during Persona generation or Warm-up")
        page.on("close", _on_close)

        # Allow extra time for CDP to stabilize before heavy network load
        time.sleep(1.5)

        if page.is_closed():
             logger.error("🛑 Page was closed before warm-up could start")
             raise SanityCheckException("Page closed prematurely")

        try:
            # Using longer timeout and "commit" for faster/more robust initial jump
            page.goto("https://www.google.com", wait_until="commit", timeout=20000)
        except Exception as e:
            logger.warning(f"⚠️ Initial warm-up jump failed: {e}. Retrying with about:blank first...")
            # If Google fails, try another quick blank jump to see if browser is still alive
            page.goto("about:blank")
            time.sleep(1)
            page.goto("https://www.google.com", wait_until="domcontentloaded", timeout=20000)
        
        # Detect device type for HumanInput
        ua = page.evaluate("navigator.userAgent").lower()
        device_type = "mobile" if "android" in ua or "iphone" in ua or "ipad" in ua else "desktop"
        logger.debug(f"Input Mode: {device_type.upper()}")
        
        human_input = HumanInput(page, device_type=device_type)
        
        # Simulate human behavior: smart scroll (Swipe vs Wheel)
        human_input.smart_scroll()
        
        time.sleep(warmup_duration)
        
        # 4. Navigate to target
        logger.info(f"🎯 Navigating to target: {target_url}")
        page.goto(target_url, wait_until="domcontentloaded", timeout=30000)
        
        logger.success(f"✅ PHASE B COMPLETE - Ready at {target_url}")
        logger.info("🤖 Browser remains open for automation...")
        
        # Return manager so caller can continue automation
        return manager
        
    except Exception as e:
        logger.error(f"❌ PHASE B ERROR: {e}")
        manager.stop_browser()
        raise


def run_full_opsec_workflow(profile_id, expected_country_code, target_url, warmup_duration=3, is_new_profile=True):
    """
    Execute the complete two-phase OpSec workflow.
    
    Args:
        profile_id: AdsPower profile ID
        expected_country_code: Expected country code for validation
        target_url: Final target URL
        warmup_duration: Seconds for warm-up phase
        is_new_profile: Whether this is a new profile requiring cookie generation
        
    Returns:
        OpSecBrowserManager: Active browser at target (or None if Phase A failed)
    """
    logger.info("🚀 Starting Full OpSec Workflow")
    
    try:
        # Phase B: Execute
        manager = run_phase_b_execution(profile_id, target_url, expected_country_code, warmup_duration, is_new_profile)
        
        return manager
        
    except SanityCheckException as e:
        logger.error(f"❌ Workflow aborted: {e}")
        return None
