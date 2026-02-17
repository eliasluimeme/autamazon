"""
Amazon Signup Flow Encapsulation
"""
import time
from loguru import logger
from amazon.actions.detect_state import detect_signup_state
from amazon.actions.signup import click_create_account, fill_registration_form, handle_new_customer_intent
from amazon.actions.interstitials import handle_generic_popups
from amazon.actions.cart import handle_cart_interstitial

def run_signup_flow(playwright_page, identity, device) -> bool:
    """
    Manages the entire signup/login flow loop until success or failure.
    
    Args:
        playwright_page: Playwright page object
        identity: Identity object or dict
        device: DeviceAdapter
        
    Returns:
        True if signup/login was successful (landed on success page/state)
    """
    logger.info("🔄 Starting Unified Signup/Login Flow...")
    
    max_steps = 15 # Allow sufficient steps for multi-stage login
    
    for step_idx in range(max_steps):
        # Always handle popups between steps
        handle_generic_popups(playwright_page, device)
        
        # Detect current state
        state = detect_signup_state(playwright_page)
        current_url = playwright_page.url
        logger.info(f"🚦 Signup Flow Step {step_idx + 1}: State='{state}'")
        
        # --- SUCCESS STATE ---
        if state == "success":
            logger.success("✅ Signup/Login successful!")
            return True
            
        # --- ERROR STATE ---
        if state == "error":
            logger.error("❌ Encountered error state in signup flow")
            return False

        # --- HANDLING STATES ---
        
        # 1. Unknown / Cart / Ambiguous
        if state == "unknown":
            # Check for Kindle/ebook purchase success URLs (signup is done!)
            success_url_patterns = [
                "/kindle-dbs/clarification",
                "/kindle-dbs/thankYou",
                "/gp/digital/",
                "/gp/your-account",
                "/ref=nav_ya_signin",
                "/gp/aw/d/",
            ]
            if any(pattern in current_url for pattern in success_url_patterns):
                logger.success("✅ Signup successful! Detected post-purchase/account page.")
                return True
                
            if "/ap/signin" in current_url.lower() or "/ap/register" in current_url.lower():
                # Re-check specifically for email entry
                from amazon.actions.signin_email import is_email_signin_page
                if is_email_signin_page(playwright_page):
                    state = "email_signin_entry"
                    logger.info("Re-detected 'unknown' as 'email_signin_entry'")
                else:
                    state = "signin_choice"
                    logger.info("Re-detected 'unknown' as 'signin_choice' based on URL")
            elif "/cart" in current_url.lower() or "/gp/cart" in current_url.lower():
                logger.info("On cart page, attempting to proceed...")
                handle_cart_interstitial(playwright_page, device)
                time.sleep(2)
                continue
            else:
                logger.warning(f"Unknown state at URL: {current_url}")
                # Wait briefly and retry detection
                time.sleep(2)
                continue

        # 2. Email Entry (Variant 2 or Standard Login)
        if state == "email_signin_entry":
            logger.info("📧 Handling Email Entry...")
            from amazon.actions.signin_email import handle_email_signin_step
            if handle_email_signin_step(playwright_page, identity, device):
                time.sleep(2)
                continue
            else:
                logger.error("Failed to handle email entry")
                return False

        # 3. Signin Choice / Create Account (Variant 1)
        elif state == "signin_choice" or state == "signin":
            logger.info("🆕 Handling Sign-in Choice (Attempting Create Account)...")
            if click_create_account(playwright_page, device):
                time.sleep(2)
                continue
            else:
                # Fallback: Check if it's actually email entry (Variant 2)
                # If we couldn't find "Create account", maybe we are just on the signin form?
                logger.warning("Failed to select Create Account - Attempting fallback to Email Entry (Variant 2)")
                
                # Check for email input
                email_input = playwright_page.locator("input[name='email']").first
                if email_input.is_visible(timeout=2000):
                    logger.info("Found email input - switching to 'email_signin_entry' state")
                    state = "email_signin_entry"
                    # We will jump to email_signin_entry logic in the next iteration or right now by modifying loop?
                    # Since we are inside the loop, we can just continue, but we need to ensure the state variable update persists?
                    # The loop re-detects state at the top. We need to force it.
                    # Actually, the loop calls detect_signup_state at start.
                    # So if we simply continue, detect_signup_state needs to return email_signin_entry.
                    # It likely already returned signin_choice incorrectly.
                    
                    # To force it, we can call handle_email_signin_step DIRECTLY here
                    logger.info("📧 Executing fallback Email Entry handler immediately...")
                    from amazon.actions.signin_email import handle_email_signin_step
                    if handle_email_signin_step(playwright_page, identity, device):
                        time.sleep(2)
                        continue
                        
                logger.error("Failed to select Create Account and no Email Entry fallback found")
                return False

        # 4. New Customer Intent
        elif state == "new_customer_intent":
            logger.info("🆕 Handling New Customer Intent...")
            if handle_new_customer_intent(playwright_page, device):
                time.sleep(2)
                continue
            else:
                logger.error("Failed to handle new customer intent")
                return False

        # 5. Registration Form
        elif state == "registration_form":
            logger.info("📝 Handling Registration Form...")
            if fill_registration_form(playwright_page, identity, device):
                time.sleep(1)
                from amazon.actions.signup import click_continue_registration
                click_continue_registration(playwright_page, device)
                time.sleep(3)
                continue
            else:
                logger.error("Failed to fill registration form")
                return False

        # 6. Add Mobile Number (optional step)
        elif state == "add_mobile":
            logger.info("📱 Handling Add Mobile Number step...")
            from amazon.actions.mobile_verification import handle_add_mobile_step
            
            # Try to skip if no phone number provided
            # In the future, we can pass phone_number from identity
            phone_number = identity.get('phone', None) if hasattr(identity, 'get') else getattr(identity, 'phone', None)
            
            if handle_add_mobile_step(playwright_page, phone_number, device):
                time.sleep(2)
                continue
            else:
                logger.warning("Mobile verification step not handled, continuing...")
                time.sleep(2)
                continue

        # 7. Verification (OTP / Puzzle / Email)
        elif state == "verification" or state == "captcha" or state == "puzzle":
            logger.info(f"🔒 Handling Verification: {state}")
            
            if state == "puzzle":
                from amazon.actions.puzzle_solver import handle_puzzle_step
                if handle_puzzle_step(playwright_page):
                    time.sleep(2)
                    continue
                else:
                    logger.warning("Puzzle solver returned False")
                    # Should we fail or retry? Let's retry detection
                    continue

            if state == "captcha":
                 from amazon.captcha_solver import solve_captcha
                 solve_captcha(playwright_page)
                 time.sleep(2)
                 continue
            
            # OTP / Email Code
            # OTP / Email Code
            from amazon.actions.email_verification import handle_email_verification
            
            # Extract email safely
            email_val = identity.get('email', '') if hasattr(identity, 'get') else getattr(identity, 'email', str(identity))
            
            # Need browser context for email verification, try to get it from page
            context = playwright_page.context
            
            if handle_email_verification(context, playwright_page, device, email_val):
                 time.sleep(2)
                 continue
            else:
                 # It might return False if it needs manual intervention or failed
                 logger.warning("Email verification action returned False (might be stuck)")
                 # We don't abort immediately, maybe state updates?
                 time.sleep(5) 
                 continue

        # 7. Passkey Nudge
        elif state == "passkey_nudge":
            from amazon.actions.passkey import handle_passkey_nudge
            logger.info("🔑 Handling Passkey Nudge (Skipping)...")
            if handle_passkey_nudge(playwright_page, device):
                time.sleep(1)
            else:
                 logger.warning("Passkey handler returned False")
            continue
             
        # Add a sleep to prevent tight loops
        time.sleep(2)

    logger.error("❌ Signup flow timed out (max steps reached)")
    return False
