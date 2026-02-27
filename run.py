"""
Amazon Automation - Main Entry Point V2
Orchestrates the entire flow using SessionState and State Machines.
"""
import sys
import os
import time
import argparse
import signal
import agentql
from loguru import logger

# Configure paths
root_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(root_dir)

if root_dir not in sys.path:
    sys.path.insert(0, root_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

# Configure logging
logger.remove()
logger.add(sys.stderr, level="INFO")
logger.add("logs/automation.log", level="DEBUG", rotation="10 MB")

# Import core modules
try:
    from modules.opsec_workflow import OpSecBrowserManager
except ImportError as e:
    logger.error("Could not import OpSecBrowserManager. Check your environment/path.")
    sys.exit(1)

from amazon.core.session import SessionState
from amazon.device_adapter import DeviceAdapter
from amazon.actions.ebook_search_flow import run_ebook_search_flow
from amazon.actions.signup_flow import run_signup_flow
from amazon.actions.developer_registration import run_developer_registration
from amazon.actions.two_step_verification import run_2fa_setup_flow

def run_amazon_automation(profile_id: str, product_name: str = None):
    """Refactored main flow using session persistence and state machines."""
    logger.info(f"🚀 Initializing V2 Automation for Profile: {profile_id}")
    
    # 1. Initialize Session State
    session = SessionState(profile_id)
    session.load()
    
    # 2. Launch Browser
    manager = OpSecBrowserManager(profile_id)
    
    # Signal handler for clean exit
    def signal_handler(sig, frame):
        logger.warning(f"Received signal {sig}, cleaning up...")
        manager.stop_browser()
        sys.exit(1)
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    try:
        manager.start_browser(headless=False)
        # Handle case where context or pages might be empty
        playwright_page = None
        if manager.context and manager.context.pages:
            playwright_page = manager.context.pages[0]
        elif manager.context:
            playwright_page = manager.context.new_page()
            
        if not playwright_page:
            logger.error("Failed to acquire a page from the browser.")
            return False
            
        # 3. Detect Device
        device = DeviceAdapter(playwright_page)
        
        # --- PHASE 1: Outlook Setup (Optional but prioritized) ---
        if not session.identity and not session.completion_flags.get("outlook_created", False):
            logger.info("📬 Phase: Outlook Setup")
            from amazon.actions.outlook_flow import handle_outlook_setup
            generated_identity, new_page = handle_outlook_setup(manager, playwright_page, device)
            
            if generated_identity and new_page:
                session.update_identity(generated_identity)
                session.update_flag("outlook_created", True)
                playwright_page = new_page
                device.page = playwright_page
            else:
                logger.error("🛑 CRITICAL: Outlook setup failed. Cannot proceed without a valid identity.")
                return False

        # --- PHASE 2: eBook Selection ---
        if not session.completion_flags.get("product_selected", False):
            logger.info("🛒 Phase: Product Selection")
            if run_ebook_search_flow(playwright_page, device, session):
                session.update_flag("product_selected", True)
            else:
                logger.error("Failed at Product Selection")
                return False

        # --- PHASE 3: Signup / Login ---
        if not session.completion_flags.get("amazon_signup", False):
            logger.info("👤 Phase: Identity & Signup")
            if run_signup_flow(playwright_page, session, device):
                logger.success("✓ Signup/Login complete")
            else:
                logger.error("Failed at Signup/Login")
                return False

        # --- PHASE 4: Developer Registration ---
        if not session.completion_flags.get("dev_registration", False):
            logger.info("🛠️ Phase: Developer Registration")
            # Ensure we use the latest page (in case previous phase changed it)
            playwright_page = device.page
            if run_developer_registration(playwright_page, session, device):
                logger.success("✓ Developer Registration complete")
            else:
                logger.error("Failed at Developer Registration")
                return False

        # --- PHASE 5: 2FA Setup ---
        if not session.completion_flags.get("2fa_enabled", False):
            logger.info("🔐 Phase: 2FA Activation")
            # Ensure we use the latest page
            playwright_page = device.page
            if run_2fa_setup_flow(playwright_page, session, device):
                logger.success("✓ 2FA Activation complete")
            else:
                logger.error("Failed at 2FA Setup")
                return False

        logger.success(f"🏁 ALL PHASES COMPLETE for Profile {profile_id}")
        return True

    except Exception as e:
        logger.exception(f"Unexpected error in automation: {e}")
        return False
    finally:
        manager.stop_browser()

def main():
    parser = argparse.ArgumentParser(description="Amazon V2 Automation")
    parser.add_argument("profile_id", help="AdsPower profile ID")
    parser.add_argument("--product", "-p", help="Product to search", default=None)
    args = parser.parse_args()
    
    try:
        success = run_amazon_automation(args.profile_id, args.product)
        if not success:
            logger.error(f"Automation failed for profile {args.profile_id}")
            sys.exit(1)
        sys.exit(0)
    except SystemExit as e:
        sys.exit(e.code)
    except Exception as e:
        logger.error(f"Main execution error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
