import time
import random
import sys
import os
from loguru import logger

# Configure paths to ensure we can import our modules
root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
parent_dir = os.path.dirname(root_dir)

if root_dir not in sys.path:
    sys.path.insert(0, root_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

# Import Project Modules (Sync)
from amazon.modules.opsec_workflow import run_phase_b_execution, OpSecBrowserManager
from amazon.outlook.identity import generate_outlook_identity
from amazon.outlook.config import OUTLOOK_SIGNUP_URL
from amazon.outlook.selectors import SELECTORS
from amazon.device_adapter import DeviceAdapter
from amazon.modules.adspower import AdsPowerProfileManager
from amazon.modules.proxy import get_proxy_config

# Import Real Action Handlers from Outlook Module
from amazon.outlook.actions import (
    detect_current_step,
    handle_email_step,
    handle_password_step,
    handle_name_step,
    handle_dob_step,
    handle_privacy_step,
    handle_passkey_step,
    setup_webauthn_bypass
)

# =========================================================================
# HUMAN BEHAVIOR SIMULATION
# =========================================================================

def pre_captcha_human_behavior(page):
    """Perform random scrolls and hovers to appear human."""
    print("🧠 Simulating pre-CAPTCHA human behavior (scrolls & hovers)...")
    try:
        # 1. Random scrolls
        for _ in range(random.randint(2, 3)):
             amount = random.randint(200, 500)
             if random.random() > 0.6: amount = -amount # Occasionally scroll up
             page.mouse.wheel(0, amount)
             time.sleep(random.uniform(0.6, 1.4))
        
        # 2. Random hovers over interaction points
        elements = page.locator('a, h1, h2, label, p').all()
        if elements:
             for _ in range(random.randint(1, 2)):
                  el = random.choice(elements)
                  try:
                       if el.is_visible():
                            box = el.bounding_box()
                            if box:
                                 # Move naturally to the element
                                 page.mouse.move(
                                     box['x'] + box['width']/2 + random.randint(-10, 10), 
                                     box['y'] + box['height']/2 + random.randint(-5, 5), 
                                     steps=random.randint(15, 25)
                                 )
                                 time.sleep(random.uniform(0.4, 0.9))
                  except: pass
    except: pass

def solve_microsoft_press_and_hold_sync(page, max_retries=3):
    """
    Solves the 'Press and hold' CAPTCHA with human-like behavior.
    Includes success detection and retry logic.
    """
    for attempt in range(max_retries):
        if attempt > 0:
            print(f"🔄 Retry Attempt {attempt+1}/{max_retries}...")
            time.sleep(2)

        # Ensure the page hasn't redirected already
        if "signup" not in page.url and "live.com" not in page.url:
            print("✅ Page already redirected - assuming solved.")
            return True

        # Wait for the popup text
        try:
            page.wait_for_selector('text="Let\'s prove you\'re human"', timeout=15000)
        except:
            if "signup" not in page.url: return True
            print("⚠️ CAPTCHA text not found - checking for button anyway")

        # Locate the button
        print("🔍 Searching for 'Press and hold' button...")
        button = None
        box = None
        
        # Search for up to 10 seconds
        start_search = time.time()
        while time.time() - start_search < 12:
            # 1. Try common selectors
            selectors = [
                'button:has-text("Press and hold")',
                '[role="button"]:has-text("Press and hold")',
                'div:has-text("Press and hold")',
                '#holdButton'
            ]
            
            # Check main page and all frames
            target_page_or_frame = [page] + page.frames
            for f in target_page_or_frame:
                for sel in selectors:
                    try:
                        loc = f.locator(sel)
                        if loc.count() > 0 and loc.is_visible():
                            b = loc.bounding_box()
                            if b and b['width'] > 0:
                                button = loc
                                box = b
                                break
                    except: continue
                if button: break
            if button: break
            time.sleep(1)

        if not button or not box:
             print("❌ Could not locate button. Skipping solver.")
             return False

        # 3. Handle Obstructions (like 'Accessible challenge' popups)
        # Click the background once to clear any floating tooltips/popups
        try:
             page.mouse.click(box['x'] - 30, box['y'] - 30)
             time.sleep(0.5)
        except: pass
        
        # Target the FAR-RIGHT side of the button (85% across) 
        # This safely avoids the 'Accessible challenge' icon on the left
        target_x = box['x'] + box['width'] * 0.85 + random.randint(-10, 10)
        target_y = box['y'] + box['height'] / 2 + random.randint(-8, 8)
        
        # Simulate Human Movement to the target point
        page.mouse.move(target_x + random.randint(-20, 20),
                        target_y + random.randint(-20, 20),
                        steps=random.randint(15, 25))
        time.sleep(random.uniform(0.3, 0.6))

        # 4. PERFORM PRESS AND HOLD WITH PROGRESS MONITORING
        print(f"🖱️ Pressing at ({target_x:.1f}, {target_y:.1f}) [Far Right]...")
        page.mouse.move(target_x, target_y, steps=5)
        page.mouse.down()
        
        center_x, center_y = target_x, target_y # Update centers for jitter
        
        hold_start = time.time()
        # Behavioral target: 5.5 to 13.0 seconds
        max_hold = 16.0 
        min_hold = 4.6
        
        print(f"⏱️ Starting precision hold (Min {min_hold}s)...")
        
        # Monitor progress bar (width) and animation hints
        animation_duration = 0
        progress_reached_max_at = None
        
        # Initial jitter offset
        jitter_x, jitter_y = 0.0, 0.0
        
        while time.time() - hold_start < max_hold:
            elapsed = time.time() - hold_start
            
            # NATURAL RANDOM WALK JITTER
            # We add small increments instead of just random jumps
            jitter_x += random.uniform(-1.5, 1.5)
            jitter_y += random.uniform(-1.2, 1.2)
            # Clamp to safe radius
            jitter_x = max(-10, min(10, jitter_x))
            jitter_y = max(-8, min(8, jitter_y))
            
            page.mouse.move(center_x + jitter_x, center_y + jitter_y, steps=2)
            
            # PROGRESS DETECTION & DYNAMIC RELEASE
            if int(elapsed * 10) % 10 == 0: # Check every 1s
                try:
                    # 1. Get progress bar width
                    # 2. Extract animation duration hint from CSS (Microsoft specific)
                    progress_info = button.evaluate(r"""el => {
                        const divWithWidth = Array.from(el.querySelectorAll('div')).find(d => d.style.width && d.style.width.includes('px'));
                        const pWithAnim = Array.from(el.querySelectorAll('p')).find(p => p.style.animation);
                        
                        let animMs = 0;
                        if (pWithAnim) {
                            const match = pWithAnim.style.animation.match(/(\d+)ms/);
                            if (match) animMs = parseInt(match[1]);
                        }
                        
                        return {
                            width: divWithWidth ? parseFloat(divWithWidth.style.width) : 0,
                            animMs: animMs
                        };
                    }""")
                    
                    if progress_info['animMs'] > 0:
                         animation_duration = progress_info['animMs'] / 1000.0
                    
                    current_width = progress_info['width']
                    print(f"   [Holding... {elapsed:.1f}s | Progress: {current_width:.1f}px | Hint: {animation_duration:.1f}s]")
                    
                    # Store when we hit the max
                    if current_width >= 230 and progress_reached_max_at is None:
                         progress_reached_max_at = time.time()
                         print(f"🎯 Progress bar filled! Waiting for buffer...")

                    # RELEASE LOGIC with Mandatory Buffer
                    # We wait 1.5s AFTER the bar fills to be absolutely safe
                    if progress_reached_max_at and (time.time() - progress_reached_max_at >= 1.5):
                         if elapsed >= min_hold:
                              print("✅ Safety buffer reached. Releasing...")
                              break
                         
                    # Emergency release: if we've exceeded the animation hint significantly
                    if animation_duration > 0 and elapsed > (animation_duration + 2.5) and elapsed >= min_hold:
                         print("🎯 Animation time exceeded limit! Releasing...")
                         break
                except: pass
            
            time.sleep(0.1)

        page.mouse.up()
        print(f"✅ Mouse released after {time.time() - hold_start:.1f}s")
        
        # Post-release behavior: move away and wait
        page.mouse.move(center_x + random.randint(100, 200), center_y + random.randint(100, 200), steps=15)
        # 5. POST-HOLD DETECTION (Retry until solved)
        # Give the UI 3-5 seconds to update
        time.sleep(4)
        
        # Capture screenshot for debugging
        try:
            shot_path = f"logs/captcha_attempt_{attempt+1}.png"
            page.screenshot(path=shot_path)
            print(f"📸 Captured attempt screenshot: {shot_path}")
        except: pass

        # a) Check for Redirect (Absolute Success)
        url = page.url.lower()
        if "signup" not in url or any(k in url for k in ["privacy", "passkey", "interrupt", "verify"]):
            print("🎉 SUCCESS: Page redirected!")
            return True

        # b) Check for "Please try again" (Explicit Failure)
        error_found = False
        for f in [page] + page.frames:
            try:
                # Check for various error text variations
                error_selectors = [
                    'text="Please try again"', 
                    'text="Try again"', 
                    '.error:has-text("again")',
                    'p:has-text("again")'
                ]
                for err_sel in error_selectors:
                    err_loc = f.locator(err_sel)
                    if err_loc.count() > 0 and err_loc.is_visible():
                        print(f"❌ FAILED: Error message '{err_sel}' detected in frame.")
                        error_found = True
                        break
                if error_found: break
            except: continue
        
        if error_found:
            continue # Retry loop

        # c) KEYWORD SCANNING (The main signal)
        print("🔍 Scanning frames for remaining challenge keywords...")
        challenge_still_present = False
        try:
            # Keywords indicating the challenge is still active or failed
            keywords = ["prove", "human", "hold", "press", "again", "Try", "verification"]
            for f in [page] + page.frames:
                try:
                    # Capture all text in the frame body
                    frame_text = f.evaluate("document.body ? document.body.innerText : ''").lower()
                    for kw in keywords:
                        if kw.lower() in frame_text:
                            print(f"⚠️ Challenge keyword '{kw}' found in frame text.")
                            challenge_still_present = True
                            break
                    if challenge_still_present: break
                except: continue
        except: pass

        if challenge_still_present:
            print("⚠️ Challenge still detectable. Re-attempting...")
            # Perform a background click to 'reset' focus/tooltips for next attempt
            try: page.mouse.click(15, 15); time.sleep(1)
            except: pass
            continue # Retry loop
            
        print("🎉 SUCCESS: No challenge keywords found in any frame.")
        return True
    
    print("❌ All retry attempts exhausted.")
    return False

# =========================================================================
# TEST ORCHESTRATOR
# =========================================================================

def run_test():
    # --- CONFIG ---
    PROFILE_ID = "k1atak7y" # Re-using the profile as requested
    COUNTRY = "us"
    
    print(f"🚀 Starting Test Workflow using Profile: {PROFILE_ID}")
    
    # 1. Use existing profile via OpSec manager
    # Note: run_phase_b_execution handles launch + warmup + target navigation
    try:
        manager = run_phase_b_execution(
            profile_id=PROFILE_ID,
            target_url=OUTLOOK_SIGNUP_URL,
            country_code=COUNTRY,
            warmup_duration=3,
            is_new_profile=False # We already warmed it in previous run
        )
    except Exception as e:
        print(f"❌ OpSec Workflow failed to navigate: {e}")
        return

    if not manager or not manager.page:
        print("❌ Could not get browser page from OpSec manager")
        return

    page = manager.page
    device = DeviceAdapter(page)
    
    # Initialize AgentQL (used by some handlers)
    agentql_page = None
    try:
        import agentql
        agentql_page = agentql.wrap(page)
    except: pass
    
    # Setup WebAuthn bypass to avoid annoying popups
    setup_webauthn_bypass(page)
    
    try:
        # 2. Setup Identity
        identity = generate_outlook_identity(country_code=COUNTRY)
        # identity needs to be a dict for the handlers
        print(f"📧 Test Identity: {identity['email_handle']}@outlook.com / {identity['password']}")
        
        # 3. Pass through whole signup workflow using REAL handlers
        print("\n📍 Driving flow to CAPTCHA step using REAL handlers...")
        
        steps_taken = 0
        max_steps = 20
        reached_captcha = False
        
        while steps_taken < max_steps:
             current_state = detect_current_step(page, agentql_page)
             print(f"📍 Detected State: {current_state}")
             
             if current_state == "CAPTCHA":
                 reached_captcha = True
                 print("🎯 CAPTCHA detected! Breaking flow to execute solver...")
                 break
             
             if current_state == "SUCCESS" or current_state == "STAY_SIGNED_IN":
                 print("🏁 Reached success/stay-signed-in without CAPTCHA. Test may need fresh identity.")
                 break
             
             if current_state == "EMAIL":
                 handle_email_step(page, identity, device, agentql_page)
             elif current_state == "PASSWORD":
                 handle_password_step(page, identity, device, agentql_page)
             elif current_state == "NAME":
                 handle_name_step(page, identity, device, agentql_page)
             elif current_state == "DOB":
                 handle_dob_step(page, identity, device, agentql_page)
             elif current_state == "PRIVACY":
                 handle_privacy_step(page, device, agentql_page)
             elif current_state == "PASSKEY":
                 handle_passkey_step(page, device, agentql_page)
             else:
                  print("...Waiting for interaction or transition...")
             
             steps_taken += 1
             time.sleep(3) # Small gap for state transitions
        
        if not reached_captcha:
            print("❌ Did not reach CAPTCHA step in time.")
        else:
            # 4. PRE-CAPTCHA BEHAVIOR
            pre_captcha_human_behavior(page)
            
            # 5. EXECUTE SOLVER TEST
            print("\n" + "="*50)
            print("🚀 EXECUTING CAPTCHA SOLVER TEST")
            print("="*50)
            
            # Additional small wait for captcha to fully settle
            time.sleep(1)
            
            success = solve_microsoft_press_and_hold_sync(page, max_retries=10)
            
            if success:
                print("\n✅ TEST RESULT: Solver completed successfully!")
            else:
                print("\n❌ TEST RESULT: Solver failed.")

        print("\nTest completed. Keeping browser open for observation for 30 seconds.")
        time.sleep(30)

    except KeyboardInterrupt:
        print("\n🛑 Stopped by user.")
    except Exception as e:
        print(f"💥 Error during flow: {e}")
    finally:
        print("🧹 Cleaning up...")
        manager.stop_browser()

if __name__ == "__main__":
    run_test()
