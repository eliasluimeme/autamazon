"""
Kindle eBook Search Flow for Amazon Automation V2
"""

import time
import random
from loguru import logger

from amazon.config import DELAYS
from amazon.actions.interstitials import handle_generic_popups
from amazon.core.interaction import InteractionEngine
from amazon.core.session import SessionState

KINDLE_STORE_URL = "https://www.amazon.com/amz-books/store?ou=psf&ref_=navm_em_hmenu_top_categories_0_1_1_6&ref_=navm_em_hmenu_top_categories_0_1_1_6&node=154606011&filter=true&filters=v1%3AFORMAT%5Bkindle_edition%5D"

def detect_cart_state(page) -> str:
    """Detects current state of the ebook/cart flow."""
    url = page.url.lower()
    
    # 1. Login / Signup (Success condition for this module)
    if any(x in url for x in ["signin", "register", "ap/", "challenge", "arb="]):
        return "login_prompt"
        
    # 2. Cart Interstitial
    try:
        if "/cart" in url or "/huc/" in url or page.locator("#huc-v2-order-row-messages").is_visible(timeout=500):
            return "cart_confirm"
    except Exception: pass
        
    # 3. Product Page (Has 1-Click Buy)
    try:
        if "/dp/" in url or page.locator("#buy-now-button, #one-click-button").is_visible(timeout=500):
            return "product_page"
    except Exception: pass
        
    # 4. Search Results / Storefront
    if "/amz-books/store" in url or "s?k=" in url:
        return "storefront"
        
    return "unknown"

def run_ebook_search_flow(playwright_page, device, session: SessionState) -> bool:
    """
    State-machine driven execution of eBook checkout.
    """
    logger.info("🔄 Starting V2 eBook Search Flow (State Machine)...")
    interaction = InteractionEngine(playwright_page, device)
    
    max_steps = 15
    for step in range(max_steps):
        if playwright_page.is_closed():
            logger.error("❌ Page closed during eBook flow.")
            return False

        state = detect_cart_state(playwright_page)
        logger.info(f"🛒 eBook Flow State: {state}")
        
        handle_generic_popups(playwright_page, device)
        
        if state == "login_prompt":
            logger.success("✅ Reached Login/Signup Prompt. eBook checkout flow complete.")
            return True
            
        elif state == "unknown":
            logger.info("Navigating to Kindle Store...")
            for attempt in range(3):
                try:
                    if playwright_page.is_closed():
                        return False
                    playwright_page.goto(KINDLE_STORE_URL, wait_until="domcontentloaded", timeout=30000)
                    time.sleep(2)
                    break
                except Exception as e:
                    err_msg = str(e).lower()
                    logger.warning(f"Navigation error (Attempt {attempt+1}/3): {e}")
                    if "target page, context or browser has been closed" in err_msg:
                        return False
                    time.sleep(5)
                
        elif state == "storefront":
            logger.info("🔍 Selecting Random eBook...")
            
            # Scroll to load elements (lazy loading)
            try:
                for _ in range(2):
                    device.scroll("down", "medium")
                    time.sleep(1)
            except: pass
            
            # Select random book link
            book_selectors = [
                 "xpath=//*[@id='mobile-books-storefront_ClickPicksStrategy']//bds-unified-book-faceout//div/a",
                 "xpath=//*[@id='mobile-books-storefront_KDDDailyDealsGMS']//bds-unified-book-faceout//div/a",
                 "bds-unified-book-faceout a",
                 "bds-carousel-item a[href*='/dp/']",
                 "div[class*='faceout'] a",
                 "div.s-result-item[data-component-type='s-search-result'] a.a-link-normal.s-no-outline"
            ]
            
            selected_link = None
            for sel in book_selectors:
                try:
                    elements = playwright_page.locator(sel).all()
                    valid_links = []
                    for link in elements:
                        try:
                            box = link.bounding_box()
                            if box and box['width'] > 50 and box['height'] > 50:
                                valid_links.append(link)
                        except: continue
                    if valid_links:
                        selected_link = random.choice(valid_links)
                        break
                except Exception: continue
                    
            if selected_link:
                try: title = selected_link.inner_text().strip()
                except: title = "Ebook"
                logger.info(f"Targeting: {title[:30]}...")
                
                # Execute efficient click
                device.js_click(selected_link, "Random eBook Link")
                time.sleep(3)
                continue
            else:
                # Use standard interaction engine for AgentQL fallback
                logger.info("No standard links found, using InteractionEngine AgentQL Fallback...")
                success = interaction.smart_click(
                    "Random eBook from Storefront",
                    agentql_query="{ ebook_items[] { product_link } }",
                    biomechanical=False
                )
                if success:
                    time.sleep(3)
                else:
                    logger.error("Failed to click any eBook. Retrying navigation...")
                    playwright_page.goto(KINDLE_STORE_URL)
                    
        elif state == "product_page":
            # Execute Buy Now
            initial_url = playwright_page.url
            success = interaction.smart_click(
                description="Buy now with 1-Click Button",
                selectors=[
                    "#one-click-button",
                    "xpath=//*[@id='one-click-button']",
                    "input[name='submit.buy-now']",
                    "#buy-now-button", 
                    "span.a-button-inner:has-text('Buy now with 1-Click')",
                ],
                agentql_query="{ buy_now_1_click_button }",
                cache_key="buy_now_1_click",
                biomechanical=True
            )
            
            # Efficient Transition Check
            logger.info("⏳ Monitoring for transition after Buy Now click...")
            for _ in range(10):
                time.sleep(1)
                current_state = detect_cart_state(playwright_page)
                if current_state == "login_prompt":
                    logger.success("✅ Transitioned to Login Prompt - Buy Now Successful!")
                    return True
                if playwright_page.url != initial_url and "/ap/" in playwright_page.url:
                    logger.success("✅ URL changed to auth page - Buy Now Successful!")
                    return True
                    
            if not success:
                logger.warning("Could not execute Buy Now. Reloading storefront...")
                playwright_page.goto(KINDLE_STORE_URL)
                
        elif state == "cart_confirm":
            logger.info("Handling Cart Interstitial...")
            success = interaction.smart_click(
                "Proceed to Checkout",
                selectors=[
                    "input[name='proceedToRetailCheckout']",
                    "#sc-buy-box-ptc-button",
                    "button:has-text('Proceed to checkout')"
                ],
                biomechanical=True
            )
            time.sleep(3)
            
        time.sleep(1)

    logger.error("❌ eBook flow timed out (max steps reached)")
    return False
