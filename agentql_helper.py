"""
AgentQL Helper Utilities

Provides enhanced AgentQL functionality with:
- XPath extraction from elements
- Persistent selector caching for faster subsequent lookups
- Reliable element clicking using extracted paths
- Self-healing via cached XPath fallback
"""

import os
import json
import time
import agentql
from loguru import logger

# Try to import playwright-dompath for XPath extraction
try:
    from playwright_dompath.dompath_sync import xpath_path, css_path
    DOMPATH_AVAILABLE = True
except ImportError:
    DOMPATH_AVAILABLE = False
    logger.warning("playwright-dompath not installed. XPath extraction disabled.")


# Cache file location
CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "xpath_cache")
CACHE_FILE = os.path.join(CACHE_DIR, "amazon_selectors.json")


def _load_persistent_cache() -> dict:
    """Load the persistent selector cache from disk."""
    try:
        if os.path.exists(CACHE_FILE):
            with open(CACHE_FILE, 'r') as f:
                return json.load(f)
    except Exception as e:
        logger.debug(f"Failed to load selector cache: {e}")
    return {}


def _save_persistent_cache(cache: dict):
    """Save the selector cache to disk."""
    try:
        os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
        with open(CACHE_FILE, 'w') as f:
            json.dump(cache, f, indent=2)
    except Exception as e:
        logger.debug(f"Failed to save selector cache: {e}")


# In-memory session cache for speed
_session_cache = {}


def query_and_extract(page, query: str, cache_key: str = None) -> dict:
    """
    Query elements with AgentQL and extract XPaths/CSS selectors.
    Includes retries for server errors and robust handling for detached pages.
    """
    # 1. Check in-memory session cache
    if cache_key and cache_key in _session_cache:
        logger.debug(f"Using session cache for: {cache_key}")
        return _session_cache[cache_key]
    
    # 2. Setup Retries and Page Handling
    max_attempts = 3
    for attempt in range(max_attempts):
        try:
            # Check if page is still valid
            if page.is_closed():
                logger.error("Page is closed. Cannot query AgentQL.")
                return {}

            # Wrap page for AgentQL
            agentql_page = agentql.wrap(page) if not hasattr(page, 'query_elements') else page
            
            logger.info(f"🧠 [Attempt {attempt+1}] Querying AgentQL for: {cache_key or 'dynamic query'}...")
            response = agentql_page.query_elements(query)
            results = {}
            
            # Load persistent cache to update it
            p_cache = _load_persistent_cache()
            if cache_key and cache_key not in p_cache:
                p_cache[cache_key] = {}
            
            # Extract selectors for each element in response
            for attr_name in dir(response):
                if attr_name.startswith('_'): continue
                
                element = getattr(response, attr_name, None)
                if element is None or callable(element): continue
                
                # Basic result structure
                results[attr_name] = {
                    'element': element,
                    'xpath': None,
                    'css': None,
                }
                
                # Extract XPath if dompath is available
                if DOMPATH_AVAILABLE:
                    try:
                        xpath = xpath_path(element)
                        results[attr_name]['xpath'] = xpath
                        if cache_key:
                            p_cache[cache_key][attr_name] = {'xpath': xpath, 'timestamp': time.time()}
                    except Exception as e:
                        logger.debug(f"Could not extract XPath for {attr_name}: {e}")
            
            # Save to disk
            if cache_key and results:
                _save_persistent_cache(p_cache)
                _session_cache[cache_key] = results
                logger.info(f"✅ Cached selectors for '{cache_key}' to disk")
            
            return results

        except Exception as e:
            err_msg = str(e).lower()
            if "target page, context or browser has been closed" in err_msg or "target closed" in err_msg:
                logger.error("❌ AgentQL: Browser/Page closed abruptly.")
                break # Cannot retry if page is gone
                
            if "server error" in err_msg or "500" in err_msg or "internal server error" in err_msg:
                logger.warning(f"⚠️ AgentQL Server Error (Attempt {attempt+1}): {e}")
                if attempt < max_attempts - 1:
                    time.sleep(2 * (attempt + 1))
                    continue
            
            logger.error(f"AgentQL query failed: {e}")
            break
            
    return {}


def try_cached_selectors(page, cache_key: str, timeout: int = 2000) -> dict:
    """
    Attempt to find elements using cached XPaths from disk.
    Allows handlers to bypass AgentQL entirely if selectors are still valid.
    
    Args:
        page: Playwright page
        cache_key: Key used when caching (e.g., "amazon_signin_page")
        timeout: Visibility timeout in ms
        
    Returns:
        Dict of {element_name: locator} if all critical elements found, else empty dict
    """
    p_cache = _load_persistent_cache()
    if cache_key not in p_cache:
        return {}
    
    logger.info(f"🔄 Attempting cached selectors for: {cache_key}...")
    cached_data = p_cache[cache_key]
    locators = {}
    
    try:
        for name, data in cached_data.items():
            xpath = data.get('xpath')
            if not xpath:
                continue
            
            locator = page.locator(f"xpath={xpath}").first
            if locator.is_visible(timeout=timeout):
                locators[name] = locator
            else:
                logger.debug(f"Cached selector for '{name}' is not visible")
                return {} # Fall back to AgentQL if ANY element is missing
                
        if locators:
            logger.success(f"✅ Found all elements for '{cache_key}' via cache")
            # Wrap in same format as query_and_extract for compatibility
            return {name: {'element': loc, 'xpath': cached_data[name]['xpath']} for name, loc in locators.items()}
            
    except Exception as e:
        logger.debug(f"Cache lookup failed for {cache_key}: {e}")
    
    return {}


def find_and_click(page, query: str, element_name: str, 
                   use_js: bool = False, cache_key: str = None) -> bool:
    """Find an element via cache or AgentQL and click it."""
    results = {}
    
    # 1. Try cache first if key provided
    if cache_key:
        results = try_cached_selectors(page, cache_key)
    
    # 2. Fallback to AgentQL
    if not results:
        results = query_and_extract(page, query, cache_key)
    
    if element_name not in results:
        logger.warning(f"Element {element_name} not found")
        return False
    
    element_data = results[element_name]
    element = element_data['element']
    
    try:
        element.scroll_into_view_if_needed()
        if use_js:
            element.evaluate("el => el.click()")
        else:
            element.click()
        return True
    except Exception as e:
        logger.error(f"Click failed: {e}")
        return False


def clear_cache(key: str = None):
    """Clear selector cache (both session and disk)."""
    global _session_cache
    if key:
        _session_cache.pop(key, None)
        p_cache = _load_persistent_cache()
        p_cache.pop(key, None)
        _save_persistent_cache(p_cache)
    else:
        _session_cache = {}
        _save_persistent_cache({})


# Pre-defined queries for Amazon
AMAZON_QUERIES = {
    "intent_page": """
    {
        proceed_button(the primary yellow button to proceed to create a new account)
        create_account_link(any link or button to create a new account)
    }
    """,
    "signin_page": """
    {
        email_input(input field for email address or mobile phone number)
        password_input(input field for password)
        continue_button(button to proceed after entering email)
        create_account_link(link to create a new account)
    }
    """,
    "registration_form": """
    {
        name_input
        email_input
        password_input
        password_confirm_input
        continue_button
        create_account_button
    }
    """,
    "product_page_buttons": """
    {
        buy_now_button
        add_to_cart_button
    }
    """,
    "search_results": """
    {
        result_items[] {
            product_link
            add_to_cart_button
            is_sponsored
        }
    }
    """,
    "developer_registration_form": """
    {
        country_dropdown
        business_name_input
        address_line1_input
        city_input
        postal_code_input
        state_province_region_input
        sole_proprietorship_radio_button
        use_primary_email_checkbox
        customer_support_email_input
        phone_prefix_dropdown
        phone_number_input
        interests_other_unsure_checkbox
        agree_and_continue_button
    }
    """,
}


def query_amazon(page, query_name: str, cache: bool = True) -> dict:
    """Run a pre-defined Amazon query with multi-priority approach."""
    if query_name not in AMAZON_QUERIES:
        return {}
    
    cache_key = f"amazon_{query_name}"
    
    # 1. Try cache first
    if cache:
        results = try_cached_selectors(page, cache_key)
        if results:
            return results
    
    # 2. Fallback to AgentQL
    return query_and_extract(page, AMAZON_QUERIES[query_name], cache_key if cache else None)
