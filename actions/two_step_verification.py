"""
Amazon 2-Step Verification (2SV) Flow V2
Includes pyotp integration and state-machine orchestration.
"""
import time
import re
from loguru import logger
from amazon.core.session import SessionState
from amazon.core.interaction import InteractionEngine
from amazon.core.two_factor import generate_totp_code

TWO_SV_REGISTER_URL = "https://www.amazon.com/a/settings/approval/setup/register"

def _safe_is_visible(locator, timeout=500) -> bool:
    """Safe visibility check that never raises Patchright locator errors like 'Can't query n-th element'."""
    try:
        return locator.is_visible(timeout=timeout)
    except Exception:
        return False

def _do_otp_submission(page, interaction, otp_code) -> bool:
    """Helper to input and submit TOTP code."""
    try:
        code_field = page.locator("#ch-auth-app-code-input, #sia-totp-code, input[name='code']").first
        if not _safe_is_visible(code_field, timeout=5000):
            logger.error("OTP code field not visible for submission")
            return False
            
        # Ensure field is focused
        code_field.focus()
        code_field.fill("")
        code_field.type(otp_code, delay=50)
        time.sleep(1)
        
        # Log if there was an error message on previous attempt
        error_msg = page.locator(".a-alert-error, .sia-error-message, #auth-error-message-box").first
        if _safe_is_visible(error_msg, timeout=500):
            logger.warning(f"⚠️ Amazon reported error before submission: {error_msg.inner_text().strip()}")
        
        logger.info("Submitting OTP Verification...")
        submit_selectors = [
            "#ch-auth-app-submit-button", 
            "#sia-totp-verify-button", 
            "button:has-text('Verify OTP and continue')",
            "input[type='submit'][value*='Verify']"
        ]
        
        submitted = False
        for sel in submit_selectors:
            try:
                btn = page.locator(sel).first
                if _safe_is_visible(btn, timeout=1000):
                    logger.info(f"⚡ Trigerring 'Verify' via {sel} (Composite JS)...")
                    # 1. Direct JS Click
                    btn.evaluate("el => el.click()")
                    # 2. Multi-event dispatch (React)
                    btn.evaluate("""el => {
                        const events = ['mousedown', 'click', 'mouseup'];
                        events.forEach(name => {
                            el.dispatchEvent(new MouseEvent(name, {
                                bubbles: true,
                                cancelable: true,
                                view: window,
                                buttons: 1
                            }));
                        });
                    }""")
                    try:
                        btn.click(force=True, timeout=1500)
                    except: pass
                    submitted = True
                    break
            except: continue

        if not submitted:
             interaction.smart_click(
                "Verify and Continue", 
                selectors=submit_selectors,
                biomechanical=True
            )
        return True
    except Exception as e:
        logger.error(f"Error during OTP submission: {e}")
        return False

def detect_2fa_state(page) -> str:
    """Detect current state of the 2FA activation flow."""
    url = page.url.lower()
    
    # 1. SUCCESS (Final)
    # 2FA is on when we see 'is on', 'current status is on', or the 'Disable' button on the settings page
    is_success_url = "success" in url 
    has_success_text = _safe_is_visible(page.get_by_text("is on"), timeout=500) or \
                       _safe_is_visible(page.get_by_text("Current status is on"), timeout=500) or \
                       _safe_is_visible(page.get_by_text("Two-Step Verification (2SV) Settings"), timeout=500) or \
                       (_safe_is_visible(page.get_by_text("Enabled"), timeout=500) and _safe_is_visible(page.locator("button:has-text('Disable')"), timeout=500))
    
    if is_success_url or has_success_text:
        return "success"
        
    # 2. OTP VERIFICATION (Needs email OTP)
    # We look for text that strictly mentions email or the specific CVF input ID
    # Avoid matching setup_form by ensuring TOTP headers aren't also visible
    is_email_otp = _safe_is_visible(page.get_by_text("sent the code to your email", exact=False), timeout=500) or \
                   _safe_is_visible(page.get_by_text("Check your email", exact=False), timeout=500) or \
                   _safe_is_visible(page.locator("#cvf-input-code"), timeout=500) or \
                   _safe_is_visible(page.get_by_text("Enter verification code"), timeout=500)
                   
    if is_email_otp and not _safe_is_visible(page.locator("#sia-otp-accordion-totp-header"), timeout=300):
        return "otp_verification"

    # 3. RE-AUTH / SIGN-IN
    if "/ap/signin" in url or _safe_is_visible(page.locator("#ap_password"), timeout=500):
        return "reauth_prompt"
        
    # 4. SECURITY CHECK (Interstitial Confirm/Continue button)
    if "cvf/transactionapproval" in url or \
       _safe_is_visible(page.get_by_text("Confirm re-authentication"), timeout=500) or \
       _safe_is_visible(page.get_by_text("Proceed"), timeout=500):
        return "security_check"
        
    # 5. 2FA SETUP STAGES
    if "setup/register" in url:
        # Check if we are on the "Enroll/Verify OTP" sub-page where secret is NOT visible (retry/resume case)
        has_otp_field = _safe_is_visible(page.locator("#ch-auth-app-code-input, #sia-totp-code, input[name='code']"), timeout=500)
        has_verify_btn = _safe_is_visible(page.locator("button:has-text('Verify OTP and continue')"), timeout=500)
        
        if has_otp_field and has_verify_btn and not _safe_is_visible(page.locator("#sia-otp-accordion-totp-header"), timeout=500):
            return "verify_totp_retry"
        
        return "setup_form"
        
    if _safe_is_visible(page.locator("#sia-otp-accordion-totp-header"), timeout=500):
        return "setup_form"
        
    if "approval/setup/howto" in url or _safe_is_visible(page.locator("#enable-mfa-form-submit"), timeout=500):
        return "almost_done"
        
    # 6. PASSKEY NUDGE
    if "/claim/webauthn/nudge" in url or \
       _safe_is_visible(page.get_by_text("Use face ID, fingerprint, or PIN"), timeout=500) or \
       _safe_is_visible(page.get_by_text("Set up a passkey"), timeout=500) or \
       _safe_is_visible(page.locator("#passkey-nudge-skip-button"), timeout=500):
        return "passkey_prompt"
        
    return "unknown"

def run_2fa_setup_flow(playwright_page, session: SessionState, device) -> bool:
    """State-machine driven 2FA setup."""
    logger.info("🔄 Starting V2 2FA Setup Flow...")
    
    # User Request: Close ALL open tabs and open a fresh one for 2FA
    try:
        logger.info("🆕 Cleaning up tabs and switching to fresh one for 2FA Activation...")
        context = playwright_page.context
        
        # Open the new page FIRST to avoid closing the context
        new_page = context.new_page()
        
        # Close all other pages
        for p in context.pages:
            if p != new_page:
                try: p.close()
                except: pass
        
        playwright_page = new_page
        device.page = playwright_page
        
        # Immediate navigation as requested
        logger.info(f"Navigating to 2FA Setup: {TWO_SV_REGISTER_URL}")
        playwright_page.goto(TWO_SV_REGISTER_URL, wait_until="domcontentloaded")
        
    except Exception as e:
        logger.warning(f"Could not recycle tab for 2FA: {e}")

    interaction = InteractionEngine(playwright_page, device)
    
    if not session.identity:
        logger.error("No identity in session for 2FA")
        return False
        
    identity = session.identity
    
    max_steps = 25
    used_email_otps = set()
    passkey_failures = 0
    
    for step in range(max_steps):
        if playwright_page.is_closed():
            logger.warning("Tab closed during 2FA loop. Re-acquiring...")
            try:
                playwright_page = playwright_page.context.new_page()
                device.page = playwright_page
                interaction = InteractionEngine(playwright_page, device)
                playwright_page.goto(TWO_SV_REGISTER_URL, wait_until="domcontentloaded")
            except: return False

        state = detect_2fa_state(playwright_page)
        logger.info(f"🔒 2FA Flow State: {state}")
        
        if state == "success":
            logger.success("✅ 2FA already enabled or activation confirmed!")
            session.update_flag("2fa_enabled", True)
            return True
            
        elif state == "unknown":
            logger.info(f"Ensuring navigation to: {TWO_SV_REGISTER_URL}")
            playwright_page.goto(TWO_SV_REGISTER_URL, wait_until="domcontentloaded")
            time.sleep(3)
            
        elif state == "reauth_prompt":
            logger.info("🔐 Re-authentication required...")
            try:
                # Use standard fill + click via InteractionEngine if possible
                pwd_field = playwright_page.locator("#ap_password").first
                if _safe_is_visible(pwd_field, timeout=3000):
                    pwd_field.fill(identity.password)
                    success = interaction.smart_click(
                        "Sign In Button", 
                        selectors=["#signInSubmit", "input[type='submit']", "button[name='signIn']"], 
                        biomechanical=True
                    )
                    if success:
                        time.sleep(3)
            except Exception as e:
                logger.warning(f"Re-auth attempt failed (non-critical): {e}")
                # Fallback JS if everything else is failing
                playwright_page.evaluate(f"document.querySelector('#ap_password') && (document.querySelector('#ap_password').value = '{identity.password}')")
                
        elif state == "security_check":
            logger.info("🛡️ Handling security confirmation...")
            # Prioritize the input/button itself over the span for better JS/Physical click reliability
            success = interaction.smart_click(
                "Confirm Security Check",
                selectors=[
                    "input[name='cvf_action_proceed']", 
                    "#cvf-submit-otp-button input[type='submit']",
                    "input[value='Confirm']", 
                    "input[value='Continue']",
                    "button:has-text('Confirm')", 
                    "button:has-text('Continue')",
                    "#cvf-submit-otp-button-announce",
                    "span.a-button-inner input[type='submit']"
                ],
                agentql_query="{ confirm_button(the primary button to confirm or proceed) }",
                cache_key="cvf_security_confirm",
                biomechanical=True
            )
            
            # If state persists, try a very forceful physical tap
            if success:
                time.sleep(4) # More time for redirect
                if detect_2fa_state(playwright_page) == "security_check":
                    logger.warning("🛡️ Still on security check page. Forcing physical click...")
                    try:
                        playwright_page.locator("#cvf-submit-otp-button-announce, input[name='cvf_action_proceed']").first.click(force=True, timeout=2000)
                    except: pass
                    time.sleep(3)

        elif state == "verify_totp_retry":
            logger.info("📍 Detected OTP-only verification page (Retry/Resume state)")
            if identity.two_fa_secret:
                logger.info(f"Using previously obtained secret: {identity.two_fa_secret[:4]}...")
                secret_key = identity.two_fa_secret
                
                # Generate and input OTP
                otp_code = generate_totp_code(secret_key)
                if otp_code:
                    _do_otp_submission(playwright_page, interaction, otp_code)
                    time.sleep(5)
                else:
                    logger.error("Failed to generate OTP from stored secret")
            else:
                logger.error("Landing on OTP-only page but no secret key in identity! Attempting to reload for full setup...")
                playwright_page.goto(TWO_SV_REGISTER_URL)
                time.sleep(3)
                
        elif state == "setup_form":
            # 0. Check if we already have the secret and can proceed directly to verification
            code_input_sel = "#ch-auth-app-code-input, #sia-totp-code, input[name='code']"
            if identity.two_fa_secret and _safe_is_visible(playwright_page.locator(code_input_sel).first, timeout=1000):
                logger.info(f"Direct Verification: Found OTP input and stored secret ({identity.two_fa_secret[:4]}...). Skipping extraction.")
                otp_code = generate_totp_code(identity.two_fa_secret)
                if otp_code:
                    _do_otp_submission(playwright_page, interaction, otp_code)
                    time.sleep(5)
                    continue

            # 1. Expand Authenticator App option
            if not _safe_is_visible(playwright_page.locator(code_input_sel).first, timeout=500) and \
               not _safe_is_visible(playwright_page.get_by_text("Can't scan barcode", exact=False), timeout=500):
                
                logger.info("Opening Authenticator App section...")
                interaction.smart_click(
                    "Authenticator App Header", 
                    selectors=["#sia-otp-accordion-totp-header", "label:has-text('authenticator app')"],
                    biomechanical=True
                )
                time.sleep(2)
            else:
                logger.info("Authenticator App section already expanded.")
            
            # 2. Click "Can't scan barcode?" to reveal the manual secret key
            # Suppress errors if not found, as it might already be revealed or named differently
            interaction.smart_click(
                "Can't scan barcode link",
                selectors=["#sia-auther-cant-scan-link", "a:has-text('Can't scan')", "a:has-text('barcode')", "span:has-text('Can't scan')"],
                timeout=2000,
                suppress_errors=True
            )
            time.sleep(2)
            
            # 3. Extract Secret Key
            secret_key = _extract_secret(playwright_page)
            
            # PROMPT FIX: If secret not on page, check if we already have it in session/identity from a previous attempt/run
            if not secret_key and identity.two_fa_secret:
                logger.info(f"Secret not visible on page, but found in session: {identity.two_fa_secret[:4]}... Using stored secret.")
                secret_key = identity.two_fa_secret
            
            if secret_key:
                if not identity.two_fa_secret or identity.two_fa_secret != secret_key:
                    logger.info(f"✓ New Secret Extracted: {secret_key[:4]}... Updating session.")
                    identity.two_fa_secret = secret_key
                    session.update_identity(identity)
                else:
                    logger.info(f"✓ Using Secret: {secret_key[:4]}...")
                
                # 4. Generate Code locally
                otp_code = generate_totp_code(secret_key)
                if not otp_code:
                    logger.error("Could not generate TOTP. Is pyotp installed?")
                    return False
                    
                # 5. Input & Submit Code
                _do_otp_submission(playwright_page, interaction, otp_code)
                
                # Verification & Forceful Fallback
                logger.info("⏳ Monitoring for progression after TOTP submission...")
                time.sleep(6)
                
                current_state = detect_2fa_state(playwright_page)
                if current_state == "setup_form":
                    # Check for error messages that might explain why we're still here
                    err = playwright_page.locator(".a-alert-error, .sia-error-message, #auth-error-message-box").first
                    if _safe_is_visible(err, timeout=1000):
                        logger.error(f"❌ Verification failed: {err.inner_text().strip()}")
                        # If it's a "Code expired" or "Incorrect code", the loop will retry with a new code
                    
                    logger.warning("Still on setup form. Attempting forceful click on submit buttons...")
                    try:
                        # Try brute force multi-event click on potential submit buttons
                        targets = ["#ch-auth-app-submit-button", "#sia-totp-verify-button", "button:has-text('Verify OTP and continue')"]
                        for t in targets:
                            el = playwright_page.locator(t).first
                            if _safe_is_visible(el, timeout=500):
                                el.evaluate("el => { ['mousedown', 'click', 'mouseup'].forEach(n => el.dispatchEvent(new MouseEvent(n, {bubbles:true}))); }")
                                time.sleep(1)
                                el.click(force=True, timeout=2000)
                                time.sleep(2)
                    except: pass
            else:
                logger.warning("Secret key not found on page. Refreshing for a clean slate...")
                playwright_page.reload()
                time.sleep(3)
                
        elif state == "otp_verification":
            logger.info("📧 Email OTP Verification detected during 2FA...")
            from amazon.actions.email_verification import handle_email_verification
            success = handle_email_verification(
                playwright_page.context, 
                playwright_page, 
                device, 
                identity.email,
                purpose="reauth",
                used_otps=used_email_otps
            )
            if not success:
                logger.error("Failed to solve email OTP during 2FA")
                # We don't return False immediately as the loop might recover or retry
            time.sleep(3)

        elif state == "almost_done":
            logger.info("Finalizing 2FA activation...")
            interaction.smart_click(
                "Turn On 2SV Button",
                selectors=["#enable-mfa-form-submit", "button:has-text('Turn on')"],
                biomechanical=True
            )
            session.update_flag("2fa_enabled", True)
            time.sleep(3)
            
        elif state == "passkey_prompt":
            passkey_failures += 1
            logger.info(f"🛡️ Detected Passkey Nudge (Attempt {passkey_failures}). Bypassing...")
            
            if passkey_failures > 3:
                logger.warning("⚠️ Passkey bypass failed 3+ times. Restarting 2FA step...")
                playwright_page.goto(TWO_SV_REGISTER_URL, wait_until="domcontentloaded")
                passkey_failures = 0
                time.sleep(3)
                continue
                
            try:
                # 1. Clear potential OS/Browser modals with ESC chain
                logger.info("⌨️ Pressing ESC x3 to dismiss dialogs...")
                playwright_page.bring_to_front()
                for _ in range(3):
                    playwright_page.keyboard.press("Escape")
                    time.sleep(0.5)
                time.sleep(0.5)
                
                # 2. Attempt multi-strategy bypass
                skip_selectors = [
                    "#passkey-nudge-skip-button",
                    "button:has-text('No, keep using password')",
                    "button:has-text('Not now')",
                    "button:has-text('Skip')",
                    "a:has-text('Not now')",
                    ".cvf-nudge-skip-button",
                    "button[class*='skip']",
                    "a[class*='skip']"
                ]
                
                found = False
                for sel in skip_selectors:
                    try:
                        btn = playwright_page.locator(sel).first
                        if _safe_is_visible(btn, timeout=1000):
                            logger.info(f"✅ Found skip button with: {sel}")
                            # Try device tap first (human-like)
                            success = device.tap(btn, description=f"Passkey Skip ({sel})")
                            if success:
                                # Forceful fallback click just in case tap didn't trigger logic
                                try: btn.click(force=True, timeout=500)
                                except: pass
                                found = True
                                break
                    except: continue
                
                if not found:
                    # Final fallback: Broad JS search for common skip text
                    logger.info("🧠 Using broad JS skip fallback...")
                    playwright_page.evaluate("""() => {
                        const btns = Array.from(document.querySelectorAll('button, a, span[role="button"]'));
                        const skipBtn = btns.find(b => {
                            const t = b.innerText.toLowerCase();
                            return t.includes('no, keep using') || t.includes('not now') || t.includes('skip') || t.includes('maybe later');
                        });
                        if (skipBtn) {
                            skipBtn.click();
                            ['mousedown', 'click', 'mouseup'].forEach(n => skipBtn.dispatchEvent(new MouseEvent(n, {bubbles:true})));
                            if (skipBtn.tagName === 'A' && skipBtn.href) { window.location.href = skipBtn.href; }
                        }
                    }""")
                    
            except Exception as e:
                logger.warning(f"Failed to bypass passkey: {e}")
            time.sleep(4) # Extra time for layout shift/navigation

    return session.completion_flags.get("2fa_enabled", False)

def _extract_secret(page) -> str | None:
    """Helper to parse the Base32 secret key from the DOM."""
    try:
        # Check direct IDs common in Amazon
        selectors = [
            "#sia-totp-secret-key",
            "#sia-auth-app-secret-key",
            ".sia-auth-app-key-text"
        ]
        for sel in selectors:
            el = page.locator(sel).first
            if _safe_is_visible(el, timeout=1000):
                text = el.inner_text().strip().replace(" ", "")
                if len(text) >= 16: # Base32 secrets are usually long
                    return text
            
        # Regex search in body if selectors fail
        # This looks for uppercase alphanumeric blocks which are common for secrets
        body_text = page.inner_text("body")
        # Base32 secrets often appear in blocks of 4 separated by spaces
        # User screenshot secret has 13 blocks of 4 chars
        match = re.search(r'(([A-Z2-7]{4}\s+){4,16}[A-Z2-7]{4})', body_text)
        if match:
             return match.group(1).replace(" ", "").strip()
             
        # Catch-all regex for any 16+ uppercase A-Z2-7 string
        match = re.search(r'\b([A-Z2-7]{16,64})\b', body_text)
        if match:
             return match.group(1).strip()
             
    except: pass
    return None
