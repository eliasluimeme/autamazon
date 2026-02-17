"""
Navigation Actions for Amazon Automation

Handles URL navigation and page load waiting.
"""

import time
import random
from loguru import logger

from amazon.config import AMAZON_BASE_URL, DELAYS, MAX_PAGE_LOAD_RETRIES
from amazon.actions.interstitials import handle_generic_popups


def navigate_to_amazon(page, path: str = "") -> bool:
    """
    Navigate to Amazon.
    
    Args:
        page: Playwright page object
        path: Optional path to append (e.g., "/s" for search)
        
    Returns:
        True if navigation successful
    """
    url = f"{AMAZON_BASE_URL}{path}" if path else AMAZON_BASE_URL
    
    for attempt in range(MAX_PAGE_LOAD_RETRIES):
        try:
            logger.info(f"Navigating to {url}...")
            response = page.goto(url, wait_until="domcontentloaded", timeout=30000)
            
            if response and response.ok:
                logger.success(f"✓ Navigated to Amazon")
                wait_for_page_load(page)
                return True
            else:
                logger.warning(f"Navigation response not OK: {response.status if response else 'No response'}")
                
        except Exception as e:
            logger.warning(f"Navigation attempt {attempt + 1} failed: {e}")
            time.sleep(random.uniform(2, 4))
    
    logger.error("Failed to navigate to Amazon after retries")
    return False


def wait_for_page_load(page, additional_wait: bool = True):
    """
    Wait for page to fully load with human-like timing.
    
    Args:
        page: Playwright page object
        additional_wait: Whether to add extra delay after load
    """
    try:
        # Wait for network to be idle
        page.wait_for_load_state("networkidle", timeout=10000)
    except:
        # Timeout is OK, page might have continuous network activity
        pass
    
    if additional_wait:
        # Human-like delay
        delay_min, delay_max = DELAYS["page_load"]
        time.sleep(random.uniform(delay_min, delay_max))
    
    # Check for popups that might block interaction
    handle_generic_popups(page)


def wait_for_url_change(page, timeout: int = 10000) -> bool:
    """
    Wait for URL to change (after navigation action).
    
    Args:
        page: Playwright page object
        timeout: Max time to wait in ms
        
    Returns:
        True if URL changed
    """
    initial_url = page.url
    start_time = time.time()
    timeout_sec = timeout / 1000
    
    while time.time() - start_time < timeout_sec:
        if page.url != initial_url:
            logger.debug(f"URL changed to {page.url}")
            return True
        time.sleep(0.2)
    
    logger.warning("URL did not change within timeout")
    return False


def check_page_state(page) -> str:
    """
    Detect the current page state.
    
    Returns:
        'home', 'search_results', 'product', 'checkout', 'sign_in', 'error', or 'unknown'
    """
    url = page.url.lower()
    
    if "/s?" in url or "/s/" in url:
        return "search_results"
    elif "/dp/" in url or "/gp/product/" in url:
        return "product"
    elif "/cart" in url or "/checkout" in url or "/buy" in url:
        return "checkout"
    elif "/ap/signin" in url or "/ap/register" in url:
        return "sign_in"
    elif "error" in url or "blocked" in url:
        return "error"
    elif "amazon.com" in url and len(url.split("/")) <= 4:
        return "home"
    
    return "unknown"
