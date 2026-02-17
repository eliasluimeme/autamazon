"""
Product Selection and Purchase Actions for Amazon Automation

Handles product selection from search results and Buy Now flow.
"""

import time
import random
from loguru import logger

from amazon.config import (
    DELAYS, 
    SKIP_SPONSORED_COUNT, 
    MAX_PRODUCTS_TO_CONSIDER
)
from amazon.element_locator import ElementLocator
from amazon.device_adapter import DeviceAdapter
from amazon.amazon_selectors import get_selector
from amazon.agentql_helper import query_amazon

# Session cache for product links to avoid redundant AgentQL calls
_session_product_links = []


def is_product_unavailable(page) -> bool:
    """
    Check if the current product page shows the product as unavailable.
    
    Unavailable indicators:
    - "This item cannot be shipped to your selected delivery location"
    - "See Similar Items" button instead of Buy Now
    - "Currently unavailable"
    - "No featured offers available"
    
    Args:
        page: Playwright page object
        
    Returns:
        True if product is unavailable/unshippable
    """
    try:
        # Check for popups that might cause false unavailable state
        from amazon.actions.interstitials import handle_generic_popups
        if handle_generic_popups(page):
            time.sleep(1)
            
        # Check for unavailable text indicators
        unavailable_texts = [
            "cannot be shipped to your selected delivery location",
            "No featured offers available",
            "Currently unavailable",
            "not available for purchase",
            "See Similar Items",
            "See All Buying Options",
            "temporarily out of stock",
            "We don't know when or if this item will be back in stock",
            "Available from these sellers",
            "out of stock",
        ]
        
        content = page.content().lower()
        for text in unavailable_texts:
            if text.lower() in content:
                # Check if it's really visible and not just in some hidden script
                try:
                    # Using broad text locator for visibility check
                    if page.get_by_text(text, exact=False).first.is_visible(timeout=500):
                        logger.warning(f"Product unavailable: '{text[:50]}...'")
                        return True
                except:
                    # Fallback to pure content check if visibility check fails
                    pass
        
        # Check for "See Similar Items" or "See All Buying Options" button
        try:
            indicators = [
                "text='See Similar Items'",
                "text='See All Buying Options'",
                "#buybox-see-all-buying-choices",
            ]
            for indicator in indicators:
                if page.locator(indicator).first.is_visible(timeout=500):
                    logger.warning(f"Product unavailable: Indicator '{indicator}' present")
                    return True
        except:
            pass
        
        # Check for absence of both Buy Now and Add to Cart buttons
        buy_now_selectors = ["#buy-now-button", "#buyNow", "input[name='submit.buy-now']"]
        add_to_cart_selectors = ["#add-to-cart-button", "#addToCart", "input[name='submit.add-to-cart']"]
        
        has_buy_now = False
        has_add_to_cart = False
        
        for selector in buy_now_selectors:
            try:
                if page.locator(selector).first.is_visible(timeout=300):
                    has_buy_now = True
                    break
            except:
                continue
        
        for selector in add_to_cart_selectors:
            try:
                if page.locator(selector).first.is_visible(timeout=300):
                    has_add_to_cart = True
                    break
            except:
                continue
        
        if not has_buy_now and not has_add_to_cart:
            logger.warning("Product unavailable: Neither Buy Now nor Add to Cart button found")
            return True
            
    except Exception as e:
        logger.debug(f"Availability check error: {e}")
    
    return False



def get_search_results(page, locator: ElementLocator = None) -> list:
    """
    Get list of product results from search page.
    
    Args:
        page: Playwright page object
        locator: ElementLocator instance
        
    Returns:
        List of product locators
    """
    if locator is None:
        locator = ElementLocator(page)
    
    try:
        results = locator.find_all("results", "result_items")
        logger.info(f"Found {len(results)} search results")
        return results
    except Exception as e:
        logger.error(f"Failed to get search results: {e}")
        return []


def filter_valid_products(page, products: list, skip_sponsored: bool = True) -> list:
    """
    Filter out sponsored and invalid products.
    
    Args:
        page: Playwright page object
        products: List of product locators
        skip_sponsored: Whether to skip sponsored items
        
    Returns:
        Filtered list of valid products
    """
    valid_products = []
    sponsored_selector = get_selector("results", "sponsored_label", "universal")
    
    for i, product in enumerate(products):
        try:
            # Skip first N results (usually sponsored)
            if skip_sponsored and i < SKIP_SPONSORED_COUNT:
                logger.debug(f"Skipping product {i} (likely sponsored)")
                continue
            
            # Check if explicitly marked as sponsored
            if skip_sponsored and sponsored_selector:
                try:
                    sponsored = product.locator(sponsored_selector).first
                    if sponsored.is_visible():
                        logger.debug(f"Skipping sponsored product {i}")
                        continue
                except:
                    pass  # Not sponsored
            
            # Check if product has a clickable link
            link_selector = get_selector("results", "product_link", "universal")
            if link_selector:
                try:
                    link = product.locator(link_selector).first
                    if link.is_visible():
                        valid_products.append(product)
                except:
                    pass
            else:
                valid_products.append(product)
                
        except Exception as e:
            logger.debug(f"Error filtering product {i}: {e}")
            continue
    
    logger.info(f"Filtered to {len(valid_products)} valid products")
    return valid_products


def find_purchaseable_products(page, device: DeviceAdapter = None) -> list:
    """
    Find all products in search results that have an 'Add to cart' button.
    Returns a tuple: (sponsored_links, organic_links)
    """
    if device is None:
        device = DeviceAdapter(page)
    
    sponsored_links = []
    organic_links = []
    
    # Method 1: Multi-priority approach via AgentQL helper
    results = query_amazon(page, "search_results", cache=True)
    
    if 'result_items' in results and results['result_items']:
        logger.info(f"Found {len(results['result_items'])} result items via prioritized approach")
        for item in results['result_items']:
            link = item.get('product_link')
            if not link: continue
            
            # Check if it has an Add to Cart button (indicator of purchaseability)
            if item.get('add_to_cart_button'):
                if item.get('is_sponsored'):
                    sponsored_links.append(link)
                else:
                    organic_links.append(link)
                    
    # Fallback to direct selectors if cache/AgentQL failed
    if not organic_links:
        try:
            search_results = page.locator("[data-component-type='s-search-result']").all()
            for i, result in enumerate(search_results[:15]):
                atc_btn = result.locator("button:has-text('Add to cart'), button:has-text('Add to Cart')").first
                if atc_btn.is_visible(timeout=300):
                    link = result.locator("h2 a.a-link-normal, a.a-link-normal[href*='/dp/']").first
                    if link.count() > 0:
                        organic_links.append(link)
        except:
            pass

    return sponsored_links, organic_links


def select_random_product(page, device: DeviceAdapter = None, 
                         locator: ElementLocator = None) -> bool:
    """
    Select a random product from search results.
    Uses session cache to avoid redundant detections.
    """
    global _session_product_links
    
    if device is None:
        device = DeviceAdapter(page)
    if locator is None:
        locator = ElementLocator(page, device.device_type)
        
    # Refresh session cache if empty
    if not _session_product_links:
        logger.info("Initializing product session cache...")
        
        # Human-like scrolling to load lazy items
        for _ in range(random.randint(2, 3)):
            device.scroll("down", "medium")
            time.sleep(random.uniform(0.5, 1.0))
        device.scroll("up", "small")
        
        sponsored, organic = find_purchaseable_products(page, device, locator)
        if sponsored or organic:
            # We no longer shuffle to check products sequentially in order
            _session_product_links = sponsored + organic
            logger.info(f"Session cache initialized with {len(sponsored)} sponsored and {len(organic)} organic products (sequential mode)")
        else:
            logger.error("No purchaseable products found to populate cache")
            return False
            
    # Select next product from cache
    while _session_product_links:
        selected_link = _session_product_links.pop(0)
        
        try:
            if not selected_link.is_visible(timeout=2000):
                logger.warning("Cached product link no longer visible, skipping...")
                continue
                
            device.scroll_to_element(selected_link, "product link")
            time.sleep(0.5)
            
            href = selected_link.get_attribute("href")
            url_to_navigate = href
            if href and not href.startswith('http'):
                url_to_navigate = f"https://www.amazon.com{href}"
            
            logger.info(f"Navigating to product: {url_to_navigate[:60] if url_to_navigate else 'unknown'}...")
            
            # Click it with a fallback to direct navigation if click fails or doesn't trigger navigation
            try:
                # Store URL before click
                initial_url = page.url
                
                selected_link.click(timeout=5000)
                
                # Wait for navigation
                try:
                    page.wait_for_url("**/dp/**", timeout=5000)
                except:
                    # If URL didn't change, try navigating directly
                    if page.url == initial_url and url_to_navigate:
                        logger.warning("Click didn't trigger navigation, try navigating directly...")
                        page.goto(url_to_navigate, wait_until="domcontentloaded", timeout=15000)
            except:
                if url_to_navigate:
                    logger.warning("Link click failed, navigating directly...")
                    page.goto(url_to_navigate, wait_until="domcontentloaded", timeout=15000)
                else:
                    selected_link.evaluate("el => el.click()")
                
            time.sleep(random.uniform(*DELAYS["page_load"]))
            
            # Check success
            if "/dp/" in page.url or "/gp/product/" in page.url:
                logger.success("✓ Product page loaded")
                return True
        except Exception as e:
            logger.warning(f"Failed to navigate to cached link: {e}")
            continue
            
    logger.error("All products in session cache failed or exhausted")
    return False


def clear_product_session():
    """Clear the session-level product links."""
    global _session_product_links
    _session_product_links = []
    logger.debug("Product session cache cleared")



def click_buy_now(page, device: DeviceAdapter = None, 
                  locator: ElementLocator = None) -> bool:
    """
    Click the Buy Now button on product page.
    
    Uses multiple detection methods:
    1. Direct CSS selectors (fastest)
    2. AgentQL semantic detection
    3. JavaScript-based text search
    
    Args:
        page: Playwright page object
        device: DeviceAdapter instance
        locator: ElementLocator instance
        
    Returns:
        True if Buy Now or Add to Cart was clicked
    """
    if device is None:
        device = DeviceAdapter(page)
    if locator is None:
        locator = ElementLocator(page, device.device_type)
    
    # Check for blocking popups
    from amazon.actions.interstitials import handle_generic_popups
    handle_generic_popups(page, device)
    
    logger.info("Looking for Buy Now button...")
    
    # Human-like: scroll down to reveal product action buttons
    for _ in range(3):
        device.scroll("down", "medium")
        time.sleep(random.uniform(0.5, 0.8))
    
    # Scroll back up slightly
    device.scroll("up", "small")
    time.sleep(random.uniform(0.3, 0.6))
    
    # Method 1: Multi-priority approach via AgentQL helper (Cache -> AgentQL)
    try:
        results = query_amazon(page, "product_page_buttons", cache=True)
        
        # Try Buy Now first, then Add to Cart
        for button_key in ['buy_now_button', 'add_to_cart_button']:
            if button_key in results and results[button_key]['element']:
                element = results[button_key]['element']
                button_name = "Buy Now" if button_key == "buy_now_button" else "Add to Cart"
                
                logger.info(f"🆕 Clicking {button_name} via prioritized approach...")
                device.scroll_to_element(element, button_name)
                time.sleep(random.uniform(0.3, 0.6))
                
                try:
                    element.click()
                    time.sleep(random.uniform(*DELAYS["after_click"]))
                    return True
                except:
                    element.evaluate("el => el.click()")
                    time.sleep(random.uniform(*DELAYS["after_click"]))
                    return True
            
    except Exception as e:
        logger.debug(f"Prioritized button click failed: {e}")
    
    # Method 4: JavaScript text-based search
    logger.info("Trying JavaScript text search...")
    try:
        result = page.evaluate("""
            () => {
                // Look for Buy Now
                const buyNowTexts = ['Buy Now', 'Buy now', 'BUY NOW'];
                for (const text of buyNowTexts) {
                    // Check inputs
                    const inputs = document.querySelectorAll('input[type="submit"], input[type="button"]');
                    for (const input of inputs) {
                        if (input.value && input.value.includes(text)) {
                            input.scrollIntoView({behavior: 'smooth', block: 'center'});
                            setTimeout(() => input.click(), 300);
                            return 'buy_now';
                        }
                    }
                    // Check spans/buttons
                    const elements = document.querySelectorAll('button, span.a-button-text');
                    for (const el of elements) {
                        if (el.textContent && el.textContent.includes(text)) {
                            const button = el.closest('button') || el.closest('.a-button') || el;
                            button.scrollIntoView({behavior: 'smooth', block: 'center'});
                            setTimeout(() => button.click(), 300);
                            return 'buy_now';
                        }
                    }
                }
                
                // Look for Add to Cart
                const addToCartTexts = ['Add to Cart', 'Add to cart', 'ADD TO CART'];
                for (const text of addToCartTexts) {
                    const inputs = document.querySelectorAll('input[type="submit"], input[type="button"]');
                    for (const input of inputs) {
                        if (input.value && input.value.includes(text)) {
                            input.scrollIntoView({behavior: 'smooth', block: 'center'});
                            setTimeout(() => input.click(), 300);
                            return 'add_to_cart';
                        }
                    }
                    const elements = document.querySelectorAll('button, span.a-button-text');
                    for (const el of elements) {
                        if (el.textContent && el.textContent.includes(text)) {
                            const button = el.closest('button') || el.closest('.a-button') || el;
                            button.scrollIntoView({behavior: 'smooth', block: 'center'});
                            setTimeout(() => button.click(), 300);
                            return 'add_to_cart';
                        }
                    }
                }
                
                return null;
            }
        """)
        
        if result:
            time.sleep(0.5)  # Wait for JS click
            time.sleep(random.uniform(*DELAYS["after_click"]))
            button_name = "Buy Now" if result == "buy_now" else "Add to Cart"
            logger.success(f"✓ {button_name} clicked via JavaScript!")
            return True
            
    except Exception as e:
        logger.debug(f"JavaScript method failed: {e}")
    
    logger.error("Could not find Buy Now or Add to Cart button")
    return False


def get_product_info(page, locator: ElementLocator = None) -> dict:
    """
    Extract product information from the current page.
    
    Args:
        page: Playwright page object
        locator: ElementLocator instance
        
    Returns:
        Dict with product info
    """
    if locator is None:
        locator = ElementLocator(page)
    
    info = {}
    
    try:
        # Title
        title_elem = locator.find("product", "product_title")
        if title_elem:
            info["title"] = title_elem.text_content().strip()
        
        # Price
        price_elem = locator.find("product", "price")
        if price_elem:
            info["price"] = price_elem.text_content().strip()
        
        # Availability
        avail_elem = locator.find("product", "availability")
        if avail_elem:
            info["availability"] = avail_elem.text_content().strip()
        
        # URL
        info["url"] = page.url
        
        logger.debug(f"Product info: {info}")
        
    except Exception as e:
        logger.warning(f"Failed to extract some product info: {e}")
    
    return info
