import time
import agentql
from loguru import logger
from amazon.device_adapter import DeviceAdapter
from amazon.utils.xpath_cache import get_cached_xpath, extract_and_cache_xpath

class InteractionEngine:
    """
    Centralized interaction engine that standardizes elements discovery and execution.
    Implements a strict Click Waterfall: Cache -> Selectors -> AgentQL Fallback
    Execution Waterfall: JS Click -> Dispatch -> Biomechanical Override
    """
    
    def __init__(self, page, device: DeviceAdapter):
        self.page = page
        self.device = device
        
    def smart_click(self, description: str, selectors: list = None, agentql_query: str = None, 
                    cache_key: str = None, biomechanical: bool = False, timeout: int = 5000,
                    suppress_errors: bool = False) -> bool:
        """
        Locates and clicks an element, automatically routing through anti-bot mitigations.
        
        Args:
            description: Plain text description for logging
            selectors: List of standard Playwright selectors (CSS/XPath) to try
            agentql_query: Valid AgentQL query string if selectors fail (e.g., "{ buy_button }")
            cache_key: String key for local selector caching
            biomechanical: True if this is a high-risk button (login/buy) requiring simulated real touch
            timeout: Milliseconds to wait per selector
            suppress_errors: If True, failures to locate the element will not be logged as errors
        Returns:
            True if element was successfully interacted with
        """
        if not suppress_errors:
            logger.info(f"Targeting '{description}' via InteractionEngine...")
        
        # 1. Cache Priority
        if cache_key:
            cached_xpath = get_cached_xpath(cache_key)
            if cached_xpath:
                try:
                    element = self.page.locator(f"xpath={cached_xpath}").first
                    if element.is_visible(timeout=2000):
                        logger.info(f"✓ Found '{description}' in Cache")
                        return self._execute_click(element, description, biomechanical)
                except Exception as e:
                    logger.debug(f"Cache miss for {description}: {e}")
                    
        # 2. Sequential Standard Selectors
        if selectors:
            for sel in selectors:
                try:
                    element = self.page.locator(sel).first
                    if element.is_visible(timeout=timeout):
                        logger.info(f"✓ Found '{description}' via selector: {sel}")
                        if cache_key:
                            extract_and_cache_xpath(element, cache_key)
                        return self._execute_click(element, description, biomechanical)
                except Exception:
                    continue
                    
        # 3. AgentQL Defensive Fallback
        if agentql_query:
            logger.info(f"Falling back to AgentQL for '{description}'...")
            try:
                # Check if page is closed
                if self.page.is_closed():
                    logger.error("❌ Page is closed. Cannot execute AgentQL.")
                    return False

                aql_page = agentql.wrap(self.page)
                # Execute the semantic query
                response = aql_page.query_elements(agentql_query)
                
                if response:
                    # Dynamically get the first property returned by the query, filtered to avoid methods
                    props = [p for p in dir(response) if not p.startswith('_') and not callable(getattr(response, p))]
                    if props:
                        result = getattr(response, props[0])
                        
                        # If query returns a list (e.g., ebook_items[]), pick a random item
                        if isinstance(result, list) and len(result) > 0:
                            import random
                            item = random.choice(result)
                            # Get the first property of the item, usually the link or element itself
                            sub_props = [p for p in dir(item) if not p.startswith('_') and not callable(getattr(item, p))]
                            element = getattr(item, sub_props[0]) if sub_props else item
                        else:
                            element = result
                            
                        if element and not callable(element):
                            logger.info(f"✓ Found '{description}' via AgentQL")
                            if cache_key:
                                extract_and_cache_xpath(element, cache_key)
                            return self._execute_click(element, description, biomechanical)
            except Exception as e:
                err_msg = str(e).lower()
                if "target page, context or browser has been closed" in err_msg or "target closed" in err_msg:
                    logger.error("❌ AgentQL: Browser closed during query.")
                else:
                    logger.error(f"AgentQL query failed for {description}: {e}")
                
                
        if not suppress_errors:
            logger.error(f"❌ Could not locate '{description}'")
        return False
        
    def _execute_click(self, element, description: str, biomechanical: bool) -> bool:
        """
        Executes the click using a standardized prioritized waterfall.
        Priority: JS Click -> Biomechanical/CDP Tap -> Event Dispatch -> Standard Click
        """
        try:
            # 1. Ensure visibility and position
            element.scroll_into_view_if_needed()
            time.sleep(0.3)
        except Exception: pass
            
        # Tier 1: JS Execution (Directly triggers DOM listeners, ignores overlays)
        try:
            if self.device.js_click(element, description):
                # We give a tiny sleep for JS events to fire before we assume success
                time.sleep(0.5)
                return True
        except Exception: pass

        # Tier 2: Biomechanical Priority (High Risk / Real Human Simulation)
        if biomechanical:
            logger.info(f"Using Biomechanical Override for '{description}'")
            if self.device.tap(element, description):
                return True
        
        # Tier 3: Event Dispatcher (Middle ground)
        try:
            logger.info(f"⚡ Dispatching click event for '{description}'")
            element.dispatch_event('click', bubbles=True, cancelable=True)
            time.sleep(0.5)
            return True
        except Exception: pass
                
        # Tier 4: Physical Tap fallback (for non-biomechanical calls)
        if not biomechanical:
            if self.device.tap(element, description):
                return True
                
        # Tier 5: Standard Playwright Click (Last resort)
        try:
            logger.info(f"🖱️ Standard click for '{description}'")
            element.click(force=True, timeout=2000)
            return True
        except Exception as e:
            logger.warning(f"All click methods failed for {description}: {e}")
                
        return False
