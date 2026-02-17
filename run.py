"""
Amazon Automation - Main Entry Point

Automates product browsing and purchasing on Amazon.
Supports both mobile and desktop devices with human-like interactions.

Usage:
    python amazon/run.py <PROFILE_ID> [--product "search term"]

Example:
    python amazon/run.py k18imh7u
    python amazon/run.py k18imh7u --product "bluetooth speaker"
"""

import sys
import os
import time
import argparse
import agentql

# Configure paths
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../social-ui')))

# Configure logging
from loguru import logger
logger.remove()
logger.add(sys.stderr, level="DEBUG")

# Import automation modules
try:
    from modules.opsec_workflow import OpSecBrowserManager
except ImportError as e:
    logger.error(f"Could not import OpSecBrowserManager: {e}")
    import traceback
    logger.error(traceback.format_exc())
    sys.exit(1)

# Import amazon automation components
from amazon.config import get_random_product, DELAYS
from amazon.device_adapter import DeviceAdapter
from amazon.element_locator import ElementLocator
from amazon.actions.navigate import navigate_to_amazon, wait_for_page_load, check_page_state
from amazon.actions.search import search_product, wait_for_search_results
from amazon.actions.product import select_random_product, click_buy_now, clear_product_session, is_product_unavailable
from amazon.actions.ebook_search_flow import run_ebook_search_flow
from amazon.actions.product_search_flow import run_product_search_flow
from amazon.actions.signup import (
    click_create_account,
    detect_signup_state,
    fill_registration_form,
    click_continue_registration
)
from amazon.actions.developer_registration import (
    navigate_to_developer_registration,
    fill_developer_registration_form,
    handle_2step_verification_prompt
)
from amazon.actions.cart import handle_cart_interstitial
from amazon.identity_manager import mark_identity_used


def run_amazon_automation(profile_id: str, product_name: str = None, skip_outlook: bool = False):
    """
    Main automation workflow.
    
    Steps:
    0. Launch browser via AdsPower
    1. Detect device type (mobile/desktop)
    2. Create Outlook account
    3. Navigate to amazon.com
    4. Search for ebook
    5. Select random ebook from results
    6. Click Buy Now
    7. Click Create Account (if on sign-in page)
    
    Args:
        profile_id: AdsPower profile ID
        product_name: Optional product to search for (random if not specified)
        skip_outlook: Whether to skip Outlook signup step
    """
    logger.info("=" * 50)
    logger.info("🛒 Amazon Automation Starting")
    logger.info(f"Profile ID: {profile_id}")
    logger.info("=" * 50)
    
    # Get random product if not specified
    if product_name is None:
        product_name = get_random_product()
    logger.info(f"Target product: {product_name}")
    
    # Initialize browser manager
    manager = OpSecBrowserManager(profile_id)
    
    try:
        # Step 1: Launch browser
        logger.info("📱 Launching browser...")
        manager.start_browser(headless=False)
        playwright_page = manager.context.new_page()
        page = agentql.wrap(playwright_page)
        
        # Step 2: Detect device type BEFORE navigation
        logger.info("🔍 Detecting device type...")
        device = DeviceAdapter(playwright_page)
        locator = ElementLocator(playwright_page, device.device_type)
        
        # Step 0: Outlook Signup (if not skipped)
        generated_identity = None
        if not skip_outlook:
            from amazon.actions.outlook_flow import handle_outlook_setup
            generated_identity, new_page = handle_outlook_setup(manager, playwright_page, device)
            
            if generated_identity and new_page:
                # Update page reference
                playwright_page = new_page
                device.page = playwright_page
                locator = ElementLocator(playwright_page, device.device_type)
            else:
                return False
        
        # Step 3, 4 & 5: eBook Search and Selection Flow
        # This replaces the original product search logic
        if not run_ebook_search_flow(playwright_page, device, locator):
            logger.error("Failed to complete eBook search and selection flow")
            return False
        
        product_selected = True
        
        # Wait for page after Buy Now
        time.sleep(3)  # Give page time to redirect
        
        # Wait for network to settle
        try:
            playwright_page.wait_for_load_state("networkidle", timeout=10000)
        except:
            pass  # Timeout is OK
        
        # Step 6.5: Handle Cart Interstitial (if any)
        # If we clicked Add to Cart or redirected to cart, go to checkout
        # handle_cart_interstitial(playwright_page, device)
        # time.sleep(2)
        
        # Prepare identity (Generated from Outlook or form file)
        from amazon.identity_manager import get_next_identity, mark_identity_used
        identity = generated_identity
        if not identity:
            identity = get_next_identity()

        # Final check for address popups before starting main actions
        from amazon.actions.interstitials import handle_generic_popups
        handle_generic_popups(playwright_page, device)

        # Step 7 & 8: Unified Signup Flow
        from amazon.actions.signup_flow import run_signup_flow
        
        if not run_signup_flow(playwright_page, identity, device):
            logger.error("Signup flow failed or timed out")
            return False
            
        logger.info("✅ Signup flow managed successfully")
        
        # Step 10: Amazon Developer Registration
        logger.info("🛠️ Starting Amazon Developer Registration...")
        
        # Ensure identity exists (for testing/skipped flows)
        if 'identity' not in locals() or identity is None:
            logger.info("Identity not defined, attempting to resolve from browser session...")
            from amazon.actions.identity_sync import resolve_identity_from_session
            identity = resolve_identity_from_session(playwright_page)
            
            if not identity:
                logger.warning("Could not resolve identity execution, creating dummy identity for Developer Registration test...")
                from amazon.identity_manager import Identity
                identity = Identity(
                    firstname="Jeremy",
                    lastname="Jones", 
                    email="jeremy_c4li_04@outlook.com",
                    password="password123", # Dummy
                    address_line1="123 Example St",
                    city="Seattle",
                    state="WA",
                    zip_code="98109",
                    country="Australia",
                    phone="206-555-0199"
                )
        else:
            # Even if identity is defined, double check against session if we suspect mismatch
            # (e.g. if we just did a fresh signup, it should be correct. If we skipped lookup, it might be wrong)
            from amazon.actions.identity_sync import resolve_identity_from_session
            # Only override if we find a STRONG match that is different?
            # For now, let's just trust resolve_identity_from_session to return current if it matches or can't find better
            identity = resolve_identity_from_session(playwright_page, identity)

        # Wrap page with AgentQL for robust element finding
        # We wrap it, but we primarily use the SYNC playwright_page for interactions
        aql_page = agentql.wrap(playwright_page)
        
        # Navigate using SYNC page
        navigate_to_developer_registration(playwright_page)
        
        # # Fill form using SYNC page, with AgentQL fallback
        if fill_developer_registration_form(playwright_page, identity, device, aql_page=aql_page):
            logger.success("✓ Developer registration form submitted")
            time.sleep(5)
            # Handle 2FA prompt if it appears
            handle_2step_verification_prompt(playwright_page)
            
            logger.success("🎉 Amazon Developer Registration Complete!")
        else:
            logger.warning("⚠️ Developer registration failed or skipped")

        # --- 2FA Setup ---
        logger.info("🛠️ Setting up Amazon 2-Step Verification...")
        from amazon.actions.two_step_verification import setup_2fa
        if setup_2fa(playwright_page, identity):
            logger.success("✅ 2-Step Verification configured successfully")
        else:
            logger.warning("⚠️ 2-Step Verification setup failed")
        # ---------------------------
        
        mark_identity_used(identity, success=True, notes="Account created")
        # else:
        #     logger.error(f"❌ Automation finished without reaching success state (State: {post_signup_state})")
        #     mark_identity_used(identity, success=False, notes=f"Finished at {post_signup_state}")
        #     return False

        #     # Success!
        #     logger.success("=" * 50)
        #     logger.success("✅ Amazon Automation Complete!")
        #     logger.success(f"Product searched: {product_name}")
        #     logger.success("=" * 50)
            
            # Keep browser open for observation
        logger.info("Browser will remain open. Press Ctrl+C to close.")
        while True:
            time.sleep(1)

        
    except KeyboardInterrupt:
        logger.info("User interrupted, closing browser...")
    except Exception as e:
        logger.error(f"Automation failed: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False
    finally:
        manager.stop_browser()
    
    return True


def main():
    """Parse arguments and run automation."""
    parser = argparse.ArgumentParser(
        description="Amazon product browsing automation"
    )
    parser.add_argument(
        "profile_id",
        help="AdsPower profile ID"
    )
    parser.add_argument(
        "--product", "-p",
        help="Product to search for (random if not specified)",
        default=None
    )
    
    args = parser.parse_args()
    
    if not args.profile_id:
        logger.error("No profile ID provided")
        parser.print_help()
        sys.exit(1)
    
    run_amazon_automation(args.profile_id, args.product)


if __name__ == "__main__":
    main()
