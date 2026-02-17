"""
Cart Actions for Amazon Automation

Handles:
- Detecting "Added to Cart" confirmation pages
- Clicking "Proceed to Checkout"
- Cart page navigation
"""

import time
import random
from loguru import logger

from amazon.config import DELAYS
from amazon.device_adapter import DeviceAdapter


def handle_cart_interstitial(page, device: DeviceAdapter = None) -> bool:
    """
    Handle the page that appears after adding to cart.
    Usually contains a "Proceed to checkout" button.
    
    Args:
        page: Playwright page object
        device: DeviceAdapter instance
        
    Returns:
        True if "Proceed to checkout" was clicked
    """
    if device is None:
        device = DeviceAdapter(page)
        
    logger.info("Checking for Cart/Checkout interstitial...")
    
    try:
        # Check if we are on a cart-like page
        url = page.url.lower()
        is_cart = "/cart" in url or "/huc/" in url or "smart-wagon" in url
        
        # Look for Proceed to Checkout button
        checkout_selectors = [
            "#hlb-ptc-btn-native",
            "input[name='proceedToRetailCheckout']",
            "[data-feature-id='proceed-to-checkout-action']",
            "#sc-buy-box-ptc-button",
            "input[value='Proceed to checkout']",
            "span:has-text('Proceed to checkout')",
        ]
        
        button = None
        for selector in checkout_selectors:
            try:
                element = page.locator(selector).first
                if element.is_visible(timeout=1000):
                    button = element
                    logger.info(f"Found Checkout button with selector: {selector}")
                    break
            except:
                continue
        
        # If not found via selectors, try AgentQL
        if not button:
            try:
                from amazon.agentql_helper import query_amazon
                results = query_amazon(page, "cart_page", cache=True) # define this query later
                # Or just use dynamic query here
                import agentql
                agentql_page = agentql.wrap(page)
                response = agentql_page.query_elements("""
                {
                    proceed_to_checkout_button
                }
                """)
                if response.proceed_to_checkout_button:
                    button = response.proceed_to_checkout_button
                    logger.info("Found Checkout button via AgentQL")
            except Exception as e:
                logger.debug(f"AgentQL failed for checkout button: {e}")
        
        if button:
            logger.info("🛒 Clicking Proceed to Checkout...")
            device.scroll_to_element(button, "Proceed to Checkout")
            time.sleep(random.uniform(0.3, 0.6))
            
            try:
                button.click()
            except:
                button.evaluate("el => el.click()")
                
            time.sleep(random.uniform(*DELAYS["page_load"]))
            logger.success("✓ Proceeded to Checkout")
            return True
            
        logger.info("Proceed to Checkout button not found (might already be proceeding or on different page)")
        return False
        
    except Exception as e:
        logger.warning(f"Error handling cart interstitial: {e}")
        return False
