import sys
import os
import time
import argparse

# ==============================================================================
# DEFAULT CONFIGURATION
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

def setup_single_profile(manager, name, platform, country, group_id, open_browser, headless, apply_hardening):
    """
    Creates and configures a single profile.
    """
    logger.info(f"--- Setting up profile: {name} ---")
    
    # 1. Configure Proxy
    logger.info(f"Step 1: Generating Decodo proxy for country '{country}'...")
    proxy_config = get_proxy_config(country=country)
    
    if not proxy_config:
        logger.error(f"❌ Failed to generate proxy configuration for '{country}'.")
        return None

    # 2. Create a new profile with the proxy and specified platform
    logger.info(f"Step 2: Creating a new {platform} profile named '{name}'...")
    profile_id = manager.create_random_profile(
        name=name, 
        group_id=group_id, 
        proxy_config=proxy_config,
        fingerprint_config={"os": platform}
    )
    
    if not profile_id:
        logger.error("❌ Failed to create profile.")
        return None
    
    # 3. Apply Hardening
    if apply_hardening:
        logger.info("Step 3: Applying OS-specific hardening...")
        inspection = manager.inspect_profile_live(profile_id)
        system = inspection.get("system", "Unknown")
        
        logger.info(f"Detected System: {system}")
        hardening_config = manager.generate_hardening_config(system)
        
        if manager.apply_hardening(profile_id, hardening_config, system):
            logger.success("✅ Hardening applied successfully")
        else:
            logger.warning("⚠️ Hardening application failed")

    # 4. Open Browser
    if open_browser:
        logger.info(f"Step 4: Opening the browser (Headless={headless})...")
        headless_val = 1 if headless else 0
        manager.start_profile(profile_id, headless=headless_val, open_tabs=1)
        logger.success(f"🎊 Browser is now open for profile {profile_id}")
    else:
        logger.success(f"🎊 Profile created: {profile_id}")
    
    return profile_id

def main():
    parser = argparse.ArgumentParser(description="AdsPower Profile Setup Script")
    parser.add_argument("--count", "-c", type=int, default=1, help="Number of profiles to create (default: 1)")
    parser.add_argument("--name", "-n", type=str, default=PROFILE_NAME, help=f"Base name for the profiles (default: {PROFILE_NAME})")
    parser.add_argument("--platform", "-p", type=str, default=PLATFORM, choices=["android", "ios", "windows", "mac", "linux"], help=f"Target platform (default: {PLATFORM})")
    parser.add_argument("--country", type=str, default=COUNTRY, help=f"Proxy country code (default: {COUNTRY})")
    parser.add_argument("--no-open", action="store_true", help="Don't open the browser after creation")
    parser.add_argument("--headless", action="store_true", default=HEADLESS, help="Run browser in headless mode")
    parser.add_argument("--no-hardening", action="store_false", dest="apply_hardening", default=APPLY_HARDENING, help="Skip OS-specific hardening")
    
    args = parser.parse_args()

    logger.info(f"🚀 Starting AdsPower Profile Setup for {args.count} profile(s)...")
    
    manager = AdsPowerProfileManager()
    
    created_ids = []
    for i in range(args.count):
        # Add index suffix if count > 1
        current_name = f"{args.name}_{i+1}" if args.count > 1 else args.name
        
        profile_id = setup_single_profile(
            manager=manager,
            name=current_name,
            platform=args.platform,
            country=args.country,
            group_id=GROUP_ID,
            open_browser=not args.no_open,
            headless=args.headless,
            apply_hardening=args.apply_hardening
        )
        
        if profile_id:
            created_ids.append(profile_id)
            if args.count > 1 and i < args.count - 1:
                # Small delay between multiple creations to avoid API rate limits or timing issues
                time.sleep(2)

    if created_ids:
        logger.success(f"✅ Successfully created {len(created_ids)} profile(s): {' '.join(created_ids)}")
    else:
        logger.error("❌ No profiles were created.")

if __name__ == "__main__":
    main()
