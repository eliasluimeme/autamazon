"""
Standard Product Search Flow for Amazon Automation
"""

import time
import random
from loguru import logger

from amazon.config import DELAYS, get_random_product
from amazon.actions.navigate import navigate_to_amazon, check_page_state
from amazon.actions.search import search_product, wait_for_search_results
from amazon.actions.product import (
    select_random_product, 
    click_buy_now, 
    is_product_unavailable,
    clear_product_session
)
from amazon.actions.interstitials import handle_generic_popups

def run_product_search_flow(playwright_page, device, locator, product_name=None) -> bool:
    """
    Standard search and product selection flow.
    
    Args:
        playwright_page: Playwright page object
        device: DeviceAdapter instance
        locator: ElementLocator instance
        product_name: Optional product to search for
        
    Returns:
        True if product selected and Buy Now clicked
    """
    # Step 3: Navigate to Amazon
    logger.info("🌐 Navigating to Amazon...")
    if not navigate_to_amazon(playwright_page):
        logger.error("Failed to navigate to Amazon")
        return False
    
    # Get product name if not provided
    if product_name is None:
        product_name = get_random_product()

    # Step 4: Search for product
    logger.info(f"🔍 Searching for: {product_name}")
    if not search_product(playwright_page, product_name, device, locator):
        logger.error("Failed to search for product")
        return False
    
    # Clear product session for new search
    clear_product_session()
    
    # Wait for search results
    if not wait_for_search_results(playwright_page, locator):
        logger.error("No search results found")
        return False
    
    # Step 5: Sequential product check with retry loop
    MAX_PRODUCT_RETRIES = 10
    product_selected = False
    
    for product_attempt in range(MAX_PRODUCT_RETRIES):
        logger.info(f"🔍 Checking product {product_attempt + 1}/{MAX_PRODUCT_RETRIES}...")
        locator.clear_cache()
        
        if not select_random_product(playwright_page, device, locator):
            logger.error("Failed to select product")
            return False
        
        # Verify we're on product page
        state = check_page_state(playwright_page)
        if state != "product":
            logger.warning(f"Expected product page, got: {state}")
        
        if is_product_unavailable(playwright_page):
            logger.warning(f"⚠️ Product unavailable, going back to select another...")
            
            if product_attempt < MAX_PRODUCT_RETRIES - 1:
                try:
                    playwright_page.go_back(wait_until="domcontentloaded", timeout=15000)
                    time.sleep(2)
                    wait_for_search_results(playwright_page, locator)
                    time.sleep(1)
                except Exception as e:
                    logger.warning(f"Failed to go back: {e}")
                    search_url = f"https://www.amazon.com/s?k={product_name.replace(' ', '+')}"
                    playwright_page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
                    time.sleep(2)
                continue
            else:
                logger.error("❌ All product attempts failed - no available products found")
                return False
        
        # Product is available - try to click Buy Now
        logger.info("🛒 Clicking Buy Now...")
        locator.clear_cache()
        
        if click_buy_now(playwright_page, device, locator):
            product_selected = True
            break
        else:
            logger.warning("Buy Now/Add to Cart failed, trying another product...")
            
            if product_attempt < MAX_PRODUCT_RETRIES - 1:
                try:
                    playwright_page.go_back(wait_until="domcontentloaded", timeout=10000)
                    time.sleep(1)
                except Exception as e:
                    logger.warning(f"Failed to go back: {e}")
                    search_url = f"https://www.amazon.com/s?k={product_name.replace(' ', '+')}"
                    playwright_page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
                
                wait_for_search_results(playwright_page, locator)
                continue
    
    return product_selected
