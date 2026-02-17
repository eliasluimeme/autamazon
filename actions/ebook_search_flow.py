"""
Kindle eBook Search Flow for Amazon Automation
"""

import time
import random
from loguru import logger

from amazon.config import DELAYS
from amazon.actions.navigate import wait_for_page_load
from amazon.actions.interstitials import handle_generic_popups
from amazon.agentql_helper import query_and_extract
from amazon.utils.xpath_cache import extract_and_cache_xpath, get_cached_xpath

KINDLE_STORE_URL = "https://www.amazon.com/amz-books/store?ou=psf&ref_=navm_em_hmenu_top_categories_0_1_1_6&ref_=navm_em_hmenu_top_categories_0_1_1_6&node=154606011&filter=true&filters=v1%3AFORMAT%5Bkindle_edition%5D"

EBOOK_LIST_QUERY = """
{
    ebook_links[] {
        link
        title
    }
}
"""

BUY_NOW_1_CLICK_QUERY = """
{
    buy_now_1_click_button
}
"""

def run_ebook_search_flow(playwright_page, device, locator) -> bool:
    """
    Kindle eBook specific search and selection flow.
    
    Steps:
    1. Navigate to Kindle Store
    2. Select a random ebook
    3. Click "Buy now with 1-Click" on product page
    
    Args:
        playwright_page: Playwright page object
        device: DeviceAdapter instance
        locator: ElementLocator instance
        
    Returns:
        True if ebook selected and Buy Now clicked
    """
    # Step 3: Navigate to Kindle Store
    logger.info("🌐 Navigating to Kindle Store...")
    
    max_retries = 3
    for attempt in range(max_retries):
        try:
            playwright_page.goto(KINDLE_STORE_URL, wait_until="domcontentloaded", timeout=45000)
            time.sleep(3)
            # handle_generic_popups(playwright_page, device)
            break # Success
        except Exception as e:
            logger.warning(f"Failed to navigate to Kindle Store (Attempt {attempt+1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                wait_time = (attempt + 1) * 2 # Exponential backoff: 2s, 4s, 6s...
                time.sleep(wait_time)
            else:
                logger.error(f"Failed to navigate to Kindle Store after {max_retries} attempts")
                return False

    # Step 4: Find a random ebook
    logger.info("🔍 Finding a random ebook...")
    
    # Scroll down to ensure content loads (lazy loading)
    try:
        for _ in range(2):
            device.scroll("down", "medium")
            time.sleep(1)
    except:
        pass
    
    try:
        # 1. Try selectors first - prioritizing user-provided and observed structure
        ebook_selectors = [
            # User provided specific XPaths
            "xpath=//*[@id='mobile-books-storefront_ClickPicksStrategy']//bds-unified-book-faceout//div/a",
            "xpath=//*[@id='mobile-books-storefront_KDDDailyDealsGMS']//bds-unified-book-faceout//div/a",
            
            # Generic bds- structure (Mobile Storefront)
            "bds-unified-book-faceout a",
            "bds-carousel-item a[href*='/dp/']",
            
            # Additional mobile specific
            "div[class*='faceout'] a",
            
            # Standard search results
            "div.s-result-item[data-component-type='s-search-result'] a.a-link-normal.s-no-outline",
            # Carousel/Grid items (common on Storefronts)
            "div.a-carousel-card a[href*='/dp/']",
            "li.a-carousel-card a[href*='/dp/']",
            "div.a-cardui a[href*='/dp/']",
            # Generic product links
            "a:has-text('Kindle Edition')",
            "a[href*='/dp/']:has-text('$')", # Links with price
            "a[href*='/dp/']" # Catch-all (check visibility later)
        ]
        
        links = []
        for selector in ebook_selectors:
            found_elements = playwright_page.locator(selector).all()
            if found_elements:
                # Filter to only visible links that look like products (have some height/width)
                valid_links = []
                for link in found_elements:
                    try:
                        if link.is_visible():
                            # bounding_box check to avoid tiny hidden links
                            box = link.bounding_box()
                            if box and box['width'] > 50 and box['height'] > 50:
                                valid_links.append(link)
                    except:
                        continue
                
                if valid_links:
                    links = valid_links
                    logger.info(f"Found {len(links)} ebooks via selector: {selector}")
                    break
        
        ebook_selected = False
        
        if links:
            # Pick a random one from the visible links
            selected_link = random.choice(links)
            device.scroll_to_element(selected_link, "ebook link")
            
            # Extract title if possible for logging
            try:
                title = selected_link.text_content().strip()
                if not title:
                     title = selected_link.locator("img").get_attribute("alt")
                logger.info(f"Selected ebook: {title[:50] if title else 'Unknown'}...")
            except:
                logger.info("Selected ebook (title unknown)")
                
            selected_link.click()
            time.sleep(random.uniform(*DELAYS["page_load"]))
            ebook_selected = True # Successfully selected
            
        if not ebook_selected:
            # 2. Fallback to AgentQL
            logger.info("Falling back to AgentQL for ebook links...")
            # Use a simpler query that might match the storefront better
            EBOOK_STORE_QUERY = """
            {
                ebook_items[] {
                    product_link
                    product_title
                }
            }
            """
            results = query_and_extract(playwright_page, EBOOK_STORE_QUERY, cache_key="kindle_store_ebooks_v2")
            if 'ebook_items' in results and results['ebook_items']['element']:
                ebook_list = results['ebook_items']['element']
                if ebook_list and len(ebook_list) > 0:
                    selected_ebook = random.choice(ebook_list)
                    
                    # Try to get title safely
                    title = "Unknown"
                    if hasattr(selected_ebook, 'product_title'):
                         try: title = selected_ebook.product_title.text_content()
                         except: pass
                    
                    logger.info(f"Selected ebook (AgentQL): {title}")
                    
                    # Click the link
                    selected_ebook.product_link.click()
                    time.sleep(random.uniform(*DELAYS["page_load"]))
                    ebook_selected = True
                else:
                    logger.error("No ebooks found via AgentQL")
            else:
                 logger.error("AgentQL returned no ebook links")
                 
        if not ebook_selected:
            logger.error("Failed to select any ebook")
            return False
            
    except Exception as e:
        logger.error(f"Error finding/selecting ebook: {e}")
        return False

    # Step 5: Click "Buy now with 1-Click"
    logger.info("🛒 Clicking 'Buy now with 1-Click'...")
    
    # 0. Pre-check: Are we already on the signup page?
    # Sometimes detection is slow or previous clicks worked
    if any(x in playwright_page.url.lower() for x in ["signin", "register", "ap/", "challenge", "arb="]):
        logger.info("✅ Already on signup/login page - skipping 'Buy Now' click")
        return True

    # 1. Try cached XPath first
    cached_xpath = get_cached_xpath("buy_now_1_click")
    if cached_xpath:
        try:
            element = playwright_page.locator(f"xpath={cached_xpath}").first
            if element.is_visible(timeout=2000):
                logger.info("Using cached XPath for Buy now with 1-Click")
                device.scroll_to_element(element, "Buy now with 1-Click")
                element.click()
                time.sleep(2)
                
                # Check navigation
                if any(x in playwright_page.url.lower() for x in ["signin", "register", "ap/", "challenge", "arb="]):
                     return True
                     
                return True
        except:
            logger.debug("Cached XPath for 1-Click button failed")

    # 2. Try direct selectors and text matching
    # Use a loop to retry finding the button as it might render late
    logger.info("Looking for 1-Click button...")
    
    start_time = time.time()
    while time.time() - start_time < 10:
        # Loop Check: Did we navigate?
        if any(x in playwright_page.url.lower() for x in ["signin", "register", "ap/", "challenge", "arb="]):
            logger.info("✅ Detected navigation to signup/login page")
            return True

        # A. Try exact text match (very reliable for "Buy now with 1-Click")
        try:
            # Look for button or span with exact text
            element = playwright_page.get_by_text("Buy now with 1-Click", exact=False).first
            if element.is_visible():
                logger.info("Found 1-Click button via text match")
                
                # Refine element to be the clickable container if possible
                try:
                    # If we found a span, try to get the parent button/link/input
                    clickable = element.locator("xpath=./ancestor-or-self::*[self::a or self::button or self::input or contains(@class, 'a-button-input')][1]").first
                    if clickable.is_visible():
                        logger.info("Refined to clickable ancestor")
                        element = clickable
                except:
                    pass
                    
                device.scroll_to_element(element, "Buy now with 1-Click")
                
                # Cache valid selector/xpath
                extract_and_cache_xpath(element, "buy_now_1_click")
                
                # Strategy 1: JS Click (Primary as per user preference)
                click_success = False
                try:
                    logger.info("⚡ Executing JS click...")
                    device.js_click(element, "Buy now with 1-Click (Text Match)")
                    click_success = True
                except:
                    pass

                # Strategy 2: Dispatch Click (Fallback)
                if not click_success:
                    try:
                        logger.info("⚡ Dispatching click event...")
                        element.dispatch_event('click', bubbles=True, cancelable=True)
                        click_success = True
                    except:
                        pass
                
                # Strategy 3: Mouse Click (Robust)
                if not click_success:
                    try:
                        box = element.bounding_box()
                        if box:
                            logger.info("🖱️ Mouse clicking center of element...")
                            playwright_page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
                            click_success = True
                    except: pass
                    
                time.sleep(2)
                
                # Check for navigation success (signin or register page)
                url = playwright_page.url.lower()
                if any(x in url for x in ["signin", "register", "ap/", "challenge", "arb="]):
                    logger.info("✅ 'Buy Now' click triggered navigation (Success)")
                    return True
                
                # Check if element is still visible/attached
                try:
                    if not element.is_visible():
                        logger.info("✅ 'Buy Now' button disappeared (Assumed Success due to navigation)")
                        return True
                except:
                    # If is_visible fails, element is detached -> Success
                    logger.info("✅ 'Buy Now' button detached (Assumed Success)")
                    return True

                # Retry with force click if click didn't navigate AND element is still there
                logger.warning("Click (Text Match) didn't trigger navigation, retrying with force click...")
                try:
                    element.click(force=True, timeout=3000)
                    time.sleep(2)
                    
                    url = playwright_page.url.lower()
                    if any(x in url for x in ["signin", "register", "ap/", "challenge"]):
                        logger.info("✅ 'Buy Now' force click triggered navigation (Success)")
                        return True
                except Exception as e:
                    # If force click fails because element is gone/detached, that's actually success!
                    err_msg = str(e).lower()
                    if "detached" in err_msg or "target closed" in err_msg or "can't query n-th element" in err_msg:
                        logger.info("✅ 'Buy Now' force click 'failed' due to navigation/detach (Success)")
                        return True
                    logger.warning(f"Force click failed: {e}")
                    
                return True # Assume success if no error, subsequent checks will verify 
        except:
            # If outer try fails, continue loop
            pass
            
        # B. Try user provided XPath and other selectors
        one_click_selectors = [
            "#one-click-button", # User provided (priority)
            "xpath=//*[@id='one-click-button']", # User provided
            "xpath=//*[@id='a-autoid-4']/span", # User provided previously
            "xpath=//span[contains(@id, 'a-autoid')]//span[contains(text(), 'Buy now with 1-Click')]",
            "input[name='submit.buy-now']",
            "#buy-now-button", 
            "#oneClickBuyButton",
            "button[name='submit.buy-now']",
            "span.a-button-inner:has-text('Buy now with 1-Click')"
        ]
        
        for selector in one_click_selectors:
            try:
                element = playwright_page.locator(selector).first
                if element.is_visible():
                    logger.info(f"Found 1-Click button via selector: {selector}")
                    device.scroll_to_element(element, "Buy now with 1-Click")
                    
                    # Cache valid selector/xpath
                    extract_and_cache_xpath(element, "buy_now_1_click")
                    
                    # Strategy 1: Dispatch Click (Fast)
                    click_success = False
                    try:
                        logger.info("⚡ Dispatching click event...")
                        element.dispatch_event('click', bubbles=True, cancelable=True)
                        click_success = True
                    except:
                        pass
                    
                    # Strategy 2: Mouse Click (Robust)
                    if not click_success:
                        try:
                            box = element.bounding_box()
                            if box:
                                logger.info("🖱️ Mouse clicking center of element...")
                                playwright_page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
                                click_success = True
                        except: pass
                        
                    # Strategy 3: JS Click (Fallback)
                    if not click_success:
                        device.js_click(element, "Buy now with 1-Click")

                    time.sleep(2)
                    
                    # Check for navigation success
                    url = playwright_page.url.lower()
                    if any(x in url for x in ["signin", "register", "ap/", "challenge"]):
                        logger.info("✅ 'Buy Now' click triggered navigation (Success)")
                        return True
                    
                    # Check if element is still visible/attached
                    try:
                        if not element.is_visible():
                            logger.info("✅ 'Buy Now' button disappeared (Assumed Success due to navigation)")
                            return True
                    except:
                        # If is_visible fails, element is detached -> Success
                        logger.info("✅ 'Buy Now' button detached (Assumed Success)")
                        return True

                    # Retry with force click if initial click didn't navigate AND element is still visible
                    logger.warning("Click didn't trigger navigation, retrying with force click...")
                    try:
                        element.click(force=True, timeout=3000)
                        time.sleep(2)
                        
                        url = playwright_page.url.lower()
                        if any(x in url for x in ["signin", "register", "ap/", "challenge"]):
                            logger.info("✅ 'Buy Now' force click triggered navigation (Success)")
                            return True
                    except Exception as e:
                        # If force click fails because element is gone/detached, that's actually success!
                        err_msg = str(e).lower()
                        if "detached" in err_msg or "target closed" in err_msg or "can't query n-th element" in err_msg:
                            logger.info("✅ 'Buy Now' force click 'failed' due to navigation/detach (Success)")
                            return True
                        logger.warning(f"Force click failed: {e}")
                        
                    return True # Assume success if no error, subsequent checks will verify
            except:
                continue
        
        time.sleep(1)

    # 3. Fallback to AgentQL
    logger.info("Trying AgentQL for 1-Click button...")
    try:
        results = query_and_extract(playwright_page, BUY_NOW_1_CLICK_QUERY, cache_key="one_click_button")
        if 'buy_now_1_click_button' in results and results['buy_now_1_click_button']['element']:
            element_data = results['buy_now_1_click_button']
            element = element_data['element']
            
            logger.success("Found 1-Click button via AgentQL")
            device.scroll_to_element(element, "Buy now with 1-Click")
            
            # Cache the XPath for future runs
            try:
                extract_and_cache_xpath(element, "buy_now_1_click")
            except:
                pass
            
            # Strategy 1: JS Click (Primary as per user preference)
            click_success = False
            try:
                logger.info("⚡ Executing JS click (AgentQL)...")
                device.js_click(element, "Buy now with 1-Click (AgentQL)")
                click_success = True
            except:
                pass

            # Strategy 2: Dispatch Click (Fallback)
            if not click_success:
                try:
                    logger.info("⚡ Dispatching click event (AgentQL)...")
                    element.dispatch_event('click', bubbles=True, cancelable=True)
                    click_success = True
                except:
                    pass
                
            # Strategy 3: Mouse Click (Robust)
            if not click_success:
                try:
                    box = element.bounding_box()
                    if box:
                        logger.info("🖱️ Mouse clicking center of element (AgentQL)...")
                        playwright_page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
                        click_success = True
                except: pass
            
            time.sleep(2)
            
            # Check results
            url = playwright_page.url.lower()
            if any(x in url for x in ["signin", "register", "ap/", "challenge", "arb="]):
                logger.success("✅ AgentQL click successful (Navigated)")
                return True
            
            return True # Assume success
    except Exception as e:
        logger.error(f"AgentQL for 1-Click failed: {e}")

    # Final Debug / Last Resort
    logger.error("Could not find 'Buy now with 1-Click' button - Dumping debug info...")
    try:
        # Check if button is inside an iframe
        frames = playwright_page.frames
        logger.info(f"Checking {len(frames)} iframes...")
        for frame in frames:
            try:
                btn = frame.locator("#one-click-button, #buy-now-button").first
                if btn.is_visible():
                    logger.info(f"Found button in iframe: {frame.url}")
                    btn.click()
                    return True
            except:
                pass
                
        # Dump HTML of potential container areas
        html_segment = playwright_page.locator("#buybox, #rightCol").inner_html()
        logger.debug(f"Buybox HTML snippet: {html_segment[:500]}...")
    except:
        pass

    logger.error("Could not find 'Buy now with 1-Click' button")
    return False
