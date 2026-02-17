"""
Element Locator for Amazon Automation

Implements selector-first strategy with AgentQL fallback.
Minimizes AgentQL token usage by trying CSS selectors first.
"""

import agentql
from loguru import logger

from amazon.amazon_selectors import get_selector, get_all_selectors_for_element
from amazon.queries import (
    SEARCH_PAGE_QUERY,
    RESULTS_PAGE_QUERY,
    PRODUCT_PAGE_QUERY,
    SEARCH_INPUT_QUERY,
    SEARCH_BUTTON_QUERY,
    BUY_NOW_QUERY,
    ADD_TO_CART_QUERY,
)
from amazon.config import MAX_SELECTOR_RETRIES, MAX_AGENTQL_RETRIES, ELEMENT_WAIT_TIMEOUT


class ElementLocator:
    """
    Handles element finding with selector-first strategy.
    Falls back to AgentQL only when CSS selectors fail.
    """
    
    def __init__(self, page, device_type: str = "universal"):
        """
        Initialize element locator.
        
        Args:
            page: Playwright page object (will be wrapped for AgentQL if needed)
            device_type: 'mobile', 'desktop', or 'universal'
        """
        self.page = page
        self.device_type = device_type
        self._agentql_page = None  # Lazy-loaded AgentQL wrapped page
        self._element_cache = {}   # Cache for found elements
    
    @property
    def agentql_page(self):
        """Lazy-load AgentQL wrapped page."""
        if self._agentql_page is None:
            self._agentql_page = agentql.wrap(self.page)
        return self._agentql_page
    
    def find(self, page_context: str, element_key: str, timeout: int = None) -> object:
        """
        Find an element using selector-first strategy.
        
        Args:
            page_context: 'search', 'results', 'product', 'checkout'
            element_key: The element identifier (e.g., 'search_input', 'buy_now_button')
            timeout: Override default wait timeout
            
        Returns:
            Playwright locator for the element, or None if not found
        """
        timeout = timeout or ELEMENT_WAIT_TIMEOUT
        cache_key = f"{page_context}:{element_key}"
        
        # Check cache first
        if cache_key in self._element_cache:
            cached = self._element_cache[cache_key]
            try:
                if cached.is_visible():
                    logger.debug(f"Using cached element: {element_key}")
                    return cached
            except:
                # Cache invalid, continue to find
                del self._element_cache[cache_key]
        
        # Step 1: Try CSS selectors
        element = self._find_by_selector(page_context, element_key, timeout)
        if element:
            self._element_cache[cache_key] = element
            return element
        
        # Step 2: Fallback to AgentQL
        logger.info(f"Selector failed for {element_key}, trying AgentQL...")
        element = self._find_by_agentql(page_context, element_key)
        if element:
            self._element_cache[cache_key] = element
            return element
        
        logger.error(f"Could not find element: {page_context}.{element_key}")
        return None
    
    def _find_by_selector(self, page_context: str, element_key: str, timeout: int) -> object:
        """
        Try to find element using CSS selectors.
        
        Returns:
            Playwright locator if found and visible, None otherwise
        """
        # Get device-specific selector first
        selector = get_selector(page_context, element_key, self.device_type)
        
        if selector:
            for attempt in range(MAX_SELECTOR_RETRIES):
                try:
                    locator = self.page.locator(selector).first
                    locator.wait_for(state="visible", timeout=timeout // (attempt + 1))
                    logger.debug(f"✓ Found {element_key} via selector: {selector[:50]}...")
                    return locator
                except Exception as e:
                    logger.debug(f"Selector attempt {attempt + 1} failed: {e}")
        
        # Try all alternative selectors
        all_selectors = get_all_selectors_for_element(page_context, element_key)
        for selector in all_selectors:
            try:
                locator = self.page.locator(selector).first
                locator.wait_for(state="visible", timeout=timeout // 2)
                logger.debug(f"✓ Found {element_key} via fallback selector")
                return locator
            except:
                continue
        
        return None
    
    def _find_by_agentql(self, page_context: str, element_key: str) -> object:
        """
        Find element using AgentQL semantic query.
        
        Uses batched queries when possible to minimize API calls.
        """
        # Map element keys to their queries
        query_map = {
            ("search", "search_input"): SEARCH_INPUT_QUERY,
            ("search", "search_button"): SEARCH_BUTTON_QUERY,
            ("product", "buy_now_button"): BUY_NOW_QUERY,
            ("product", "add_to_cart_button"): ADD_TO_CART_QUERY,
        }
        
        # Get specific query or use page-level batched query
        query = query_map.get((page_context, element_key))
        
        if not query:
            # Use batched page query
            page_queries = {
                "search": SEARCH_PAGE_QUERY,
                "results": RESULTS_PAGE_QUERY,
                "product": PRODUCT_PAGE_QUERY,
            }
            query = page_queries.get(page_context)
        
        if not query:
            logger.warning(f"No AgentQL query for {page_context}.{element_key}")
            return None
        
        for attempt in range(MAX_AGENTQL_RETRIES + 1):
            try:
                response = self.agentql_page.query_elements(query)
                
                # Extract the specific element from response
                element = getattr(response, element_key, None)
                
                if element:
                    logger.info(f"✓ Found {element_key} via AgentQL")
                    return element
                else:
                    logger.debug(f"AgentQL returned None for {element_key}")
                    
            except Exception as e:
                logger.warning(f"AgentQL attempt {attempt + 1} failed: {e}")
        
        return None
    
    def find_all(self, page_context: str, element_key: str) -> list:
        """
        Find all matching elements (e.g., search results).
        
        Args:
            page_context: Page context
            element_key: Element identifier
            
        Returns:
            List of locators
        """
        selector = get_selector(page_context, element_key, self.device_type)
        
        if selector:
            try:
                locators = self.page.locator(selector).all()
                logger.debug(f"Found {len(locators)} elements for {element_key}")
                return locators
            except Exception as e:
                logger.warning(f"find_all failed for {element_key}: {e}")
        
        return []
    
    def clear_cache(self):
        """Clear the element cache (call after page navigation)."""
        self._element_cache = {}
        logger.debug("Element cache cleared")
    
    def find_with_custom_selector(self, selector: str, description: str = "element") -> object:
        """
        Find element with a custom selector (bypass the selector map).
        
        Args:
            selector: CSS selector string
            description: Description for logging
            
        Returns:
            Playwright locator or None
        """
        try:
            locator = self.page.locator(selector).first
            locator.wait_for(state="visible", timeout=ELEMENT_WAIT_TIMEOUT)
            logger.debug(f"✓ Found {description} via custom selector")
            return locator
        except Exception as e:
            logger.debug(f"Custom selector failed for {description}: {e}")
            return None
