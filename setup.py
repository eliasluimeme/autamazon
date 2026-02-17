import sys
import os
import time

# ==============================================================================
# CONFIGURATION
# ==============================================================================
PROFILE_NAME = "Mobile_Setup_Profile"  # Name of the AdsPower profile
PLATFORM = "android"                   # Target platform: android or ios (for phone)
COUNTRY = "au"                         # Proxy country (us, be, fr, de, it, ca, etc.)
GROUP_ID = "0"                         # AdsPower Group ID (default "0")
OPEN_BROWSER = True                    # Open the browser immediately after setup
HEADLESS = False                       # If OPEN_BROWSER is True, run in background?
APPLY_HARDENING = True                 # Automatically apply OS-specific hardening
# ==============================================================================

# Add the current directory to sys.path so we can import 'auto'
sys.path.append(os.getcwd())

try:
    from modules.adspower import AdsPowerProfileManager
    from modules.proxy import get_proxy_config
    from loguru import logger
except ImportError as e:
    print(f"❌ Error: Could not import necessary modules. {e}")
    print("Ensure you are running this script from the project root directory.")
    sys.exit(1)

def main():
    """
    Creates a new browser profile, connects a proxy, and opens the browser.
    """
    logger.info("🚀 Starting AdsPower Profile Setup...")
    
    manager = AdsPowerProfileManager()
    
    # 1. Configure Proxy
    logger.info(f"Step 1: Generating Decodo proxy for country '{COUNTRY}'...")
    proxy_config = get_proxy_config(country=COUNTRY)
    
    if not proxy_config:
        logger.error("❌ Failed to generate proxy configuration. Check your .env file for DECODO credentials.")
        return

    # 2. Create a new profile with the proxy and specified platform
    logger.info(f"Step 2: Creating a new {PLATFORM} profile named '{PROFILE_NAME}' with proxy...")
    profile_id = manager.create_random_profile(
        name=PROFILE_NAME, 
        group_id=GROUP_ID, 
        proxy_config=proxy_config,
        fingerprint_config={"os": PLATFORM}
    )
    
    if not profile_id:
        logger.error("❌ Failed to create profile. Ensure AdsPower is running and Decodo credentials are valid.")
        return
    
    # 3. Apply Hardening (Optional but recommended)
    if APPLY_HARDENING:
        logger.info("Step 4: Applying OS-specific hardening...")
        # Inspect live helps detect the OS/UA AdsPower assigned
        inspection = manager.inspect_profile_live(profile_id)
        system = inspection.get("system", "Unknown")
        
        logger.info(f"Detected System: {system}")
        hardening_config = manager.generate_hardening_config(system)
        
        if manager.apply_hardening(profile_id, hardening_config, system):
            logger.success("✅ Hardening applied successfully")
        else:
            logger.warning("⚠️ Hardening application failed")

    # 4. Open Browser
    if OPEN_BROWSER:
        logger.info(f"Step 5: Opening the browser (Headless={HEADLESS})...")
        headless_val = 1 if HEADLESS else 0
        # open_tabs=1 to ensure at least one tab is open
        manager.start_profile(profile_id, headless=headless_val, open_tabs=1)
        logger.success(f"🎊 Setup complete! Browser is now open for profile {profile_id}")
    else:
        logger.success(f"🎊 Setup complete! Profile ID: {profile_id}")

    logger.info("You can manage this profile in the AdsPower Desktop application.")

if __name__ == "__main__":
    main()
