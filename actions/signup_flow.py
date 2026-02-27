"""
Amazon Signup Flow Encapsulation V2
State-machine based loop for handling signup, login, and verification steps.
"""
import time
from loguru import logger
from amazon.actions.detect_state import detect_signup_state
from amazon.actions.signup import click_create_account, fill_registration_form, handle_new_customer_intent, click_continue_registration
from amazon.actions.interstitials import handle_generic_popups
from amazon.actions.cart import handle_cart_interstitial
from amazon.core.session import SessionState
from amazon.core.interaction import InteractionEngine
from amazon.actions.ebook_search_flow import detect_cart_state

def run_signup_flow(playwright_page, session: SessionState, device) -> bool:
    """
    Manages the entire signup/login flow loop using SessionState for persistent data.
    """
    logger.info("🔄 Starting V2 Unified Signup/Login Flow...")
    
    # Interaction Engine for streamlined clicks/agentql fallback
    interaction = InteractionEngine(playwright_page, device)
    
    # Ensure identity is loaded
    if not session.identity:
        from amazon.identity_manager import get_next_identity
        ident = get_next_identity()
        if not ident:
            logger.error("No identity available for signup")
            return False
        session.update_identity(ident)
        
    identity = session.identity
    max_steps = 20 # Increased for robustness
    consecutive_unknown = 0
    
    for step_idx in range(max_steps):
        # 1. Popups
        handle_generic_popups(playwright_page, device)
        
        # 2. State Detection
        state = detect_signup_state(playwright_page)
        current_url = playwright_page.url
        logger.info(f"🚦 Signup Step {step_idx + 1}: State='{state}'")
        
        if state == "unknown":
            consecutive_unknown += 1
        else:
            consecutive_unknown = 0
            
        if consecutive_unknown >= 3:
            logger.warning("🔄 Stuck in 'unknown' state during signup. Resetting to retry from eBook search...")
            session.update_flag("product_selected", False)
            return False
        
        # 3. --- SUCCESS STATE ---
        if state == "success":
            logger.success("✅ Signup/Login successful!")
            session.update_flag("amazon_signup", True)
            return True
            
        # 4. Check for Product Page (Buy Now failed or redirected back)
        if detect_cart_state(playwright_page) == "product_page":
            logger.warning("📍 Detected Product Page during Signup Flow. Buy Now must have failed. Resetting for re-selection...")
            session.update_flag("product_selected", False)
            return False
            
        # --- ERROR STATE ---
        if state == "error":
            logger.error(f"❌ Encountered error state at {current_url}")
            # Try once to reload if we are stuck on an error
            playwright_page.reload()
            time.sleep(3)
            continue

        # --- HANDLING STATES ---
        
        # 1. Unknown / Cart / Ambiguous
        if state == "unknown":
            success_url_patterns = ["/kindle-dbs/", "/gp/digital/", "/gp/your-account", "ref=nav_ya_signin"]
            if any(pattern in current_url for pattern in success_url_patterns):
                logger.success("✅ Signup successful via URL detection.")
                session.update_flag("amazon_signup", True)
                return True
                
            if "/cart" in current_url.lower():
                handle_cart_interstitial(playwright_page, device)
                time.sleep(2)
                continue

        # 2. Email Entry (Variant 2 or Standard Login)
        if state == "email_signin_entry":
            logger.info("📧 Handling Email Entry...")
            from amazon.actions.signin_email import handle_email_signin_step
            # We keep current handler but pass the identity from session
            if handle_email_signin_step(playwright_page, identity, device):
                time.sleep(2)
                continue
            else:
                logger.warning("Email entry handler failed, retrying loop...")

        # 3. Signin Choice / Create Account
        elif state == "signin_choice" or state == "signin":
            logger.info("🆕 Handling Sign-in Choice (Attempting Create Account)...")
            # Upgrade: try using interaction engine for the click
            success = interaction.smart_click(
                "Create Account Button",
                selectors=["#createAccountSubmit", "#auth-create-account-link", "a:has-text('Create account')"],
                agentql_query="{ create_account_button }",
                cache_key="create_account_btn"
            )
            if success:
                time.sleep(2)
                continue
            else:
                 # Fallback to legacy handler
                 if click_create_account(playwright_page, device):
                     time.sleep(2)
                     continue

        # 4. New Customer Intent
        elif state == "new_customer_intent":
            logger.info("🆕 Handling New Customer Intent...")
            if handle_new_customer_intent(playwright_page, device):
                time.sleep(2)
                continue

        # 5. Registration Form
        elif state == "registration_form":
            logger.info("📝 Handling Registration Form...")
            if fill_registration_form(playwright_page, identity, device):
                time.sleep(1)
                # Use the robust, unified continue handler instead of ad-hoc smart_click
                if click_continue_registration(playwright_page, device):
                    time.sleep(1)
                    continue
                else:
                    logger.error("Failed to click 'Verify email' / 'Continue' even after filling form.")

        # 6. Add Mobile Number
        elif state == "add_mobile":
            from amazon.actions.mobile_verification import handle_add_mobile_step
            logger.info("📱 Skipping optional mobile number step...")
            handle_add_mobile_step(playwright_page, identity.phone, device)
            time.sleep(2)
            continue

        # 7. Verification / Captcha / Puzzle
        elif state in ["verification", "captcha", "puzzle"]:
            logger.info(f"🔒 Handling {state}...")
            
            if state == "puzzle":
                from amazon.actions.puzzle_solver import handle_puzzle_step
                handle_puzzle_step(playwright_page)
            elif state == "captcha":
                from amazon.captcha_solver import handle_captcha
                handle_captcha(playwright_page, device)
            else:
                # OTP
                from amazon.actions.email_verification import handle_email_verification
                # Pass browser context from page
                handle_email_verification(playwright_page.context, playwright_page, device, identity.email)
            
            time.sleep(2)
            continue

        # 8. Passkey Nudge
        elif state == "passkey_nudge":
            from amazon.actions.passkey import handle_passkey_nudge
            handle_passkey_nudge(playwright_page, device)
            continue
             
        time.sleep(2)

    logger.error("❌ Signup flow timed out")
    return False
