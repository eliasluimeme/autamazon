"""
Product Search Actions for Amazon Automation

Handles product search functionality.
"""

import time
import random
from loguru import logger

from amazon.config import DELAYS, get_random_product
from amazon.element_locator import ElementLocator
from amazon.device_adapter import DeviceAdapter


def search_product(page, product_name: str = None, device: DeviceAdapter = None, 
                   locator: ElementLocator = None) -> bool:
    """
    Search for a product on Amazon.
    
    Args:
        page: Playwright page object
        product_name: Product to search for (random if not specified)
        device: DeviceAdapter instance (created if not provided)
        locator: ElementLocator instance (created if not provided)
        
    Returns:
        True if search submitted successfully
    """
    # Initialize helpers if not provided
    if device is None:
        device = DeviceAdapter(page)
    if locator is None:
        locator = ElementLocator(page, device.device_type)
    
    # Get product to search
    if product_name is None:
        product_name = get_random_product()
    
    # Check for popups before typing
    from amazon.actions.interstitials import handle_generic_popups
    handle_generic_popups(page, device)
    
    logger.info(f"🔍 Searching for: {product_name}")
    
    try:
        # Find search input
        search_input = locator.find("search", "search_input")
        if not search_input:
            logger.error("Could not find search input")
            return False
        
        # Clear and focus
        device.scroll_to_element(search_input, "search input")
        time.sleep(random.uniform(*DELAYS["typing_pause"]))
        
        # Type the search term
        if not device.type_text(search_input, product_name, "search input"):
            logger.error("Failed to type search term")
            return False
        
        time.sleep(random.uniform(0.3, 0.8))
        
        # Submit search - try button first, then Enter key
        search_button = locator.find("search", "search_button")
        if search_button:
            device.tap(search_button, "search button")
        else:
            # Fallback to pressing Enter
            logger.debug("Using Enter key to submit search")
            page.keyboard.press("Enter")
        
        logger.success(f"✓ Search submitted for: {product_name}")
        return True
        
    except Exception as e:
        logger.error(f"Search failed: {e}")
        return False


def wait_for_search_results(page, locator: ElementLocator = None, timeout: int = 15000) -> bool:
    """
    Wait for search results to load.
    
    Args:
        page: Playwright page object
        locator: ElementLocator instance
        timeout: Max wait time in ms
        
    Returns:
        True if results found
    """
    if locator is None:
        locator = ElementLocator(page)
    
    logger.info("Waiting for search results...")
    
    try:
        # Wait for URL to contain search query
        start_time = time.time()
        while time.time() - start_time < timeout / 1000:
            if "/s?" in page.url or "/s/" in page.url:
                break
            time.sleep(0.3)
        
        # Wait for result items to appear
        result_item = locator.find("results", "result_items", timeout=timeout)
        
        if result_item:
            logger.success("✓ Search results loaded")
            # Additional human-like delay
            time.sleep(random.uniform(*DELAYS["after_search"]))
            return True
        
        logger.warning("No search results found")
        return False
        
    except Exception as e:
        logger.error(f"Wait for results failed: {e}")
        return False


def get_search_term_suggestions(page, partial_text: str = None) -> list:
    """
    Get search term suggestions (autocomplete).
    
    This is optional - for more human-like behavior we could
    interact with suggestions.
    
    Args:
        page: Playwright page object
        partial_text: Text to get suggestions for
        
    Returns:
        List of suggestion strings
    """
    try:
        # Amazon's autocomplete selector
        suggestions = page.locator(".s-suggestion-container .s-suggestion").all()
        return [s.text_content() for s in suggestions[:5]]
    except:
        return []
