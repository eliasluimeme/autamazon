"""
CAPTCHA Step Handler for Outlook Signup

Handles the "Press and Hold" CAPTCHA verification.
The button is typically inside NESTED IFRAMES which requires special handling.
Uses xpath_cache utility for XPath extraction and caching.
"""

import time
import random
from loguru import logger

from amazon.outlook.config import DELAYS
from amazon.outlook.utils.xpath_cache import (
    extract_and_cache_xpath,
    get_cached_xpath,
    try_cached_xpath_in_frames,
    extract_xpath_from_agentql,
    DOMPATH_AVAILABLE,
)


def handle_captcha_step(page, device, agentql_page=None) -> bool:
    """
    Handle the CAPTCHA step (Press and Hold).
    
    TEMPORARY: Automated logic disabled. 
    Polls for manual completion instead of requiring Enter key.
    """
    logger.warning("⚠️ CAPTCHA Step Detected - MANUAL INTERVENTION REQUIRED ⚠️")
    logger.warning("The automated CAPTCHA solver has been temporarily disabled.")
    logger.warning("👉 Please switch to the browser and solve the CAPTCHA manually.")
    
    try:
        # Prompt user in terminal
        print("\n" + "="*60)
        print("   >>>  PLEASE SOLVE CAPTCHA MANUALLY  <<<   ")
        print("   (Will auto-detect when solved and proceed)")
        print("="*60 + "\n")
        
        # Poll for CAPTCHA completion instead of blocking on input()
        max_wait_time = 300  # 5 minutes max
        poll_interval = 2  # Check every 2 seconds
        elapsed = 0
        
        while elapsed < max_wait_time:
            time.sleep(poll_interval)
            elapsed += poll_interval
            
            # Check if we've moved past the CAPTCHA
            try:
                url = page.url.lower()
                
                # Check for redirect to privacy notice, passkey, or success pages
                if any(indicator in url for indicator in [
                    "privacynotice",
                    "privacy",
                    "passkey",
                    "interrupt",
                    "account.microsoft.com",
                    "outlook.live.com",
                ]):
                    logger.info(f"✅ CAPTCHA solved! Detected redirect to: {url[:60]}...")
                    time.sleep(1)  # Brief settle time
                    return True
                
                # Check page content for signs we've moved on
                try:
                    page_content = page.content().lower()
                    
                    # Check for privacy/passkey page content
                    if any(indicator in page_content for indicator in [
                        "privacy notice",
                        "your privacy",
                        "setting up your passkey",
                        "stay signed in",
                    ]):
                        logger.info("✅ CAPTCHA solved! Detected next step in page content.")
                        time.sleep(1)
                        return True
                    
                    # Check if CAPTCHA elements are gone
                    if "press and hold" not in page_content and "prove you" not in page_content:
                        # Stricter double-check: wait and verify again to ensure it's not a transient state
                        time.sleep(2)
                        page_content_recheck = page.content().lower()
                        if "press and hold" not in page_content_recheck and "prove you" not in page_content_recheck:
                            # Final verification: check if we are on a known SUBSEQUENT page
                            re_url = page.url.lower()
                            if any(ind in re_url for ind in ["signup", "privacy", "passkey", "interrupt", "verify"]):
                                 # We are likely good
                                 logger.info("✅ CAPTCHA appears solved (elements no longer visible and URL is valid)")
                                 return True
                            else:
                                 # If URL is still just signup.live.com but elements are gone, check for presence of other inputs
                                 try:
                                     from amazon.outlook.actions.detect import detect_current_step
                                     next_step = detect_current_step(page)
                                     if next_step not in ["CAPTCHA", "UNKNOWN"]:
                                         logger.info(f"✅ CAPTCHA solved! Next step detected: {next_step}")
                                         return True
                                 except:
                                     pass
                            
                except Exception as e:
                    logger.debug(f"Page content check error: {e}")
                    
            except Exception as e:
                logger.debug(f"Poll check error: {e}")
            
            # Log progress every 30 seconds
            if elapsed % 30 == 0:
                logger.info(f"⏳ Still waiting for CAPTCHA... ({elapsed}s elapsed)")
        
        logger.error("CAPTCHA timeout - user did not solve within 5 minutes")
        return False
        
    except Exception as e:
        logger.error(f"CAPTCHA handling interrupted: {e}")
        return False

# -------------------------------------------------------------------------
# AUTOMATED LOGIC COMMENTED OUT BELOW
# -------------------------------------------------------------------------

# def handle_captcha_step_AUTOMATED_OLD(page, device, agentql_page=None) -> bool:
#     """
#     Handle the CAPTCHA step (Press and Hold) using simplified direct locators.
#     """
#     logger.info("🤖 Handling CAPTCHA step (Simplified Logic)")
#     
#     # User's suggested strategy: Direct frame locator + get_by_role
#     try:
#         # 1. Locate the iframe (Try both common titles/ids)
#         iframe = None
#         for selector in ["iframe[title='Verification challenge']", "iframe[data-testid='humanCaptchaIframe']"]:
#             loc = page.frame_locator(selector).first
#             try:
#                 # fast check if frame exists/is attached
#                 loc.locator("body").count() 
#                 iframe = loc
#                 logger.info(f"✅ Found CAPTCHA iframe: {selector}")
#                 break
#             except:
#                 pass
#         
#         if not iframe:
#             logger.warning("Could not find CAPTCHA iframe with standard selectors")
#             # Fallback to searching all frames just for the button if main frame not found
#             # (Leaving this as a Hail Mary, though the user wants us to try the specific one)
#             pass
#
#         if iframe:
#             # 2. Locate the button by its text and role
#             # This is much stricter and avoids containers
#             button = iframe.get_by_role("button", name="Press and hold")
#             
#             # 3. Perform the Hold
#             if button.is_visible(timeout=5000):
#                 logger.info("✅ Found 'Press and hold' button via get_by_role")
#                 
#                 box = button.bounding_box()
#                 if box:
#                     # Calculate center
#                     x = box["x"] + box["width"] / 2
#                     y = box["y"] + box["height"] / 2
#                     
#                     logger.info(f"🎯 Target coordinates: {x:.0f}, {y:.0f} (Size: {box['width']:.0f}x{box['height']:.0f})")
#                     
#                     # 4. Action (using device-specific hold to support mobile)
#                     hold_duration = random.uniform(8.0, 11.0) # Arkose usually needs ~5-10s
#                     
#                     is_mobile = device.is_mobile() if hasattr(device, 'is_mobile') else False
#                     
#                     if is_mobile:
#                         logger.info(f"📱 Performing Mobile Touch Hold ({hold_duration}s)...")
#                         success = _mobile_touch_hold(page, x, y, hold_duration)
#                     else:
#                         logger.info(f"🖱️ Performing Desktop Mouse Hold ({hold_duration}s)...")
#                         # Use the manual logic requested by user, but ensuring we use the right page context
#                         try:
#                             page.mouse.move(x, y)
#                             page.mouse.down()
#                             time.sleep(hold_duration)
#                             page.mouse.up()
#                             success = True
#                         except Exception as e:
#                             logger.error(f"Mouse hold failed: {e}")
#                             success = False
#                             
#                     if success:
#                          logger.info("✅ Hold action completed")
#                          # Wait for transition
#                          page.wait_for_timeout(5000)
#                          return _check_captcha_success(page)
#             else:
#                 logger.warning("Button not visible inside iframe")
#                 
#     except Exception as e:
#         logger.error(f"Simplified CAPTCHA handling failed: {e}")
#     
#     # Fallback to the old search method if the specific one failed
#     logger.info("Trying fallback recursive search...")
#     button_info = _find_captcha_button_in_frames(page)
#     
#     if button_info:
#         frame, locator, selector = button_info
#         logger.info(f"Found CAPTCHA button via fallback: {selector}")
#         return _perform_hold_in_frame(page, frame, locator, device)
#     
#     logger.error("CAPTCHA step failed - could not find button")
#     return False


def _find_captcha_button_in_frames(page):
    """
    Find the Press and Hold button by searching through all frames.
    Returns (frame, locator, selector) if found, None otherwise.
    """
    logger.debug("🔍 Searching for CAPTCHA button in all frames...")
    
    # 1. High-Priority Selectors (Based on User Screenshot/Analysis)
    priority_selectors = [
        "[aria-label='Press & Hold Human Challenge']",  # Exact match from screenshot
        "div[role='button']:has-text('Press and hold')", # Specific Semantic Role
        "button:has-text('Press and hold')",
        "[role='button']:has-text('Press and hold')",
        "iframe[data-testid='humanCaptchaIframe']", # Start by looking for this specific iframe
    ]
    
    # 2. General/Fallback Selectors
    general_selectors = [
        "p:has-text('Press and hold')",
        "span:has-text('Press and hold')",
        "div:has-text('Press and hold')",
        "#holdButton",
    ]
    
    all_selectors = priority_selectors + general_selectors
    
    # Get all frames including nested ones
    all_frames = page.frames
    logger.debug(f"Found {len(all_frames)} frames total")
    
    for i, frame in enumerate(all_frames):
        # logger.debug(f"Checking frame {i}: {frame.url[:60]}")
        
        for selector in all_selectors:
            # Special case for the iframe selector itself - we want to search INSIDE it
            if selector == "iframe[data-testid='humanCaptchaIframe']":
                continue
                
            try:
                # Use .all() to inspect candidates
                locators = frame.locator(selector).all()
                valid_candidate = None
                
                for loc in locators:
                    if not loc.is_visible(timeout=200):
                        continue
                        
                    box = loc.bounding_box()
                    if not box or box['width'] <= 0:
                        continue
                        
                    # Size Check: Typical button is ~250x100. Container might be larger.
                    # Screenshot: width ~234px. 
                    if box['width'] > 450 or box['height'] > 300:
                        # Too big - likely a container
                         continue

                    # Text/Role Verification
                    try:
                        # If we used a specific selector (aria-label/role), we trust it highly
                        if "aria-label" in selector or "role" in selector:
                            valid_candidate = (frame, loc, selector)
                            break
                            
                        # Otherwise verify text content
                        text = loc.text_content(timeout=200).lower()
                        if 'hold' in text or 'press' in text:
                             valid_candidate = (frame, loc, selector)
                             break
                    except:
                        pass
                
                if valid_candidate:
                    logger.info(f"✅ Confirmed CAPTCHA button: {valid_candidate[2]}")
                    return valid_candidate
                            
            except Exception:
                continue
    
    # Try using frame_locator for nested iframes (Explicit paths)
    logger.debug("Trying frame_locator approach for nested iframes...")
    
    iframe_selectors = [
        "iframe[data-testid='humanCaptchaIframe']", # User provided
        "iframe[src*='captcha']",
        "iframe[src*='arkose']",
        "iframe[src*='enforcement']",
        "iframe[title*='challenge']",
        "iframe",
    ]
    
    for iframe_sel in iframe_selectors:
        try:
            # Try first level iframe
            frame_loc = page.frame_locator(iframe_sel).first
            
            # Search for button inside
            for btn_sel in priority_selectors[:4]: # Use top 4 selectors
                try:
                    btn = frame_loc.locator(btn_sel).first
                    if btn.is_visible(timeout=500):
                         # Found it!
                         logger.info(f"Found button via frame_locator: {iframe_sel} -> {btn_sel}")
                         return (None, btn, f"frame_locator:{iframe_sel}>{btn_sel}")
                except:
                    continue
            
            # Try nested iframe (second level)
            for inner_iframe_sel in ["iframe", "iframe[src*='enforcement']", "iframe[src*='arkose']"]:
                try:
                    inner_frame = frame_loc.frame_locator(inner_iframe_sel).first
                    for btn_sel in priority_selectors[:4]:
                        try:
                            btn = inner_frame.locator(btn_sel).first
                            if btn.is_visible(timeout=500):
                                logger.info(f"Found button in nested iframe: {iframe_sel} -> {inner_iframe_sel} -> {btn_sel}")
                                return (None, btn, f"nested:{iframe_sel}>{inner_iframe_sel}>{btn_sel}")
                        except:
                            continue
                except:
                    continue
        except Exception:
            continue
    
    logger.warning("Could not find CAPTCHA button in any frame")
    return None


def _perform_hold_in_frame(page, frame, locator, device) -> bool:
    """Perform the hold action on the found button."""
    logger.info("🤖 Performing press-and-hold action...")
    
    try:
        # Get bounding box
        box = locator.bounding_box()
        if not box:
            logger.error("Could not get button bounding box")
            return False
        
        logger.debug(f"Button: x={box['x']:.0f}, y={box['y']:.0f}, size={box['width']:.0f}x{box['height']:.0f}")
        
        # Calculate target coordinates
        target_x = box['x'] + box['width'] / 2 + random.uniform(-3, 3)
        target_y = box['y'] + box['height'] / 2 + random.uniform(-3, 3)
        
        # Hold duration
        hold_duration = random.uniform(10.5, 13.0)
        logger.info(f"⏱️ Holding button for {hold_duration:.1f} seconds...")
        
        # Detect device mode
        is_mobile = device.is_mobile() if hasattr(device, 'is_mobile') else False
        
        if is_mobile:
            success = _mobile_touch_hold(page, target_x, target_y, hold_duration)
        else:
            success = _desktop_mouse_hold(page, target_x, target_y, hold_duration)
        
        if success:
            return _check_captcha_success(page)
        
        # Fallback: Try direct click with delay
        logger.debug("Trying click(delay=...) fallback")
        try:
            locator.click(delay=int(hold_duration * 1000), force=True)
            logger.info("✅ Hold completed via click(delay)")
            return _check_captcha_success(page)
        except Exception as e:
            logger.debug(f"click(delay) failed: {e}")
        
        return False
        
    except Exception as e:
        logger.error(f"Hold action failed: {e}")
        import traceback
        logger.debug(traceback.format_exc())
        return False


def _handle_via_agentql_js(page, agentql_page, device) -> bool:
    """
    Use AgentQL to find the element, then extract coordinates via JavaScript.
    This avoids the iframe locator issues.
    """
    import agentql
    
    CAPTCHA_QUERY = """
    {
        press_hold_button(the button to press and hold to verify)
    }
    """
    
    try:
        aq_page = agentql_page if agentql_page else agentql.wrap(page)
        response = aq_page.query_elements(CAPTCHA_QUERY)
        
        if not response.press_hold_button:
            logger.warning("AgentQL could not find button")
            return False
        
        logger.info("Found button via AgentQL, extracting coordinates...")
        
        # Use JavaScript to get the element's coordinates
        # AgentQL elements have internal methods we can use
        try:
            element = response.press_hold_button
            box = None
            
            # 1. Try standard bounding_box() first
            try:
                box = element.bounding_box()
            except Exception as e:
                logger.debug(f"Direct bounding_box() failed: {e}")
            
            # 2. If valid box, use it
            if box and box.get('width', 0) > 0:
                 pass # we are good
            else:
                # 3. Try JS evaluation as fallback
                try:
                    box = element.evaluate("el => { const r = el.getBoundingClientRect(); return {x: r.x, y: r.y, width: r.width, height: r.height}; }")
                except Exception as e:
                    logger.debug(f"JS evaluation failed: {e}")
            
            # 4. ID Recovery: If still no box, try to find by ID in frames (AgentQL injects IDs)
            if not (box and box.get('width', 0) > 0):
                try:
                    tf_id = element.get_attribute("tf623_id")
                    if tf_id:
                        logger.info(f"Propagating search for ID: [tf623_id='{tf_id}'] in frames")
                        for frame in page.frames:
                            try:
                                loc = frame.locator(f"[tf623_id='{tf_id}']").first
                                if loc.is_visible(timeout=200):
                                    new_box = loc.bounding_box()
                                    if new_box and new_box['width'] > 0:
                                        box = new_box
                                        logger.info(f"✅ Recovered element via ID in frame: {frame.url[:40]}...")
                                        break
                            except:
                                continue
                except Exception as e:
                    logger.debug(f"ID recovery failed: {e}")

            if box and box.get('width', 0) > 0:
                logger.debug(f"Got coordinates: {box}")
                
                target_x = box['x'] + box['width'] / 2
                target_y = box['y'] + box['height'] / 2
                hold_duration = random.uniform(10.5, 13.0)
                
                logger.info(f"⏱️ Holding at ({target_x:.0f}, {target_y:.0f}) for {hold_duration:.1f}s")
                
                is_mobile = device.is_mobile() if hasattr(device, 'is_mobile') else False
                
                if is_mobile:
                    success = _mobile_touch_hold(page, target_x, target_y, hold_duration)
                else:
                    success = _desktop_mouse_hold(page, target_x, target_y, hold_duration)
                
                if success:
                    return _check_captcha_success(page)
                    
        except Exception as e:
            logger.debug(f"Coordinate extraction failed: {e}")
        
        # Last resort: Try clicking with timeout via device
        logger.debug("Trying device.hold() as last resort")
        try:
            success = device.hold(element, duration=11.0, description="CAPTCHA button")
            if success:
                return _check_captcha_success(page)
        except Exception as e:
            logger.debug(f"device.hold failed: {e}")
        
        return False
        
    except Exception as e:
        logger.error(f"AgentQL JS approach failed: {e}")
        return False


def _mobile_touch_hold(page, x: float, y: float, duration: float) -> bool:
    """Perform a long touch hold using CDP touch events."""
    cdp = None
    try:
        logger.debug(f"📱 Mobile touch hold at ({x:.0f}, {y:.0f})")
        
        cdp = page.context.new_cdp_session(page)
        
        finger_props = {
            "x": round(x, 2),
            "y": round(y, 2),
            "radiusX": round(random.uniform(10, 15), 2),
            "radiusY": round(random.uniform(10, 15), 2),
            "force": round(random.uniform(0.5, 0.9), 3),
            "rotationAngle": round(random.uniform(30, 60), 1),
            "id": 1,
        }
        
        # Touch start
        cdp.send("Input.dispatchTouchEvent", {
            "type": "touchStart",
            "touchPoints": [finger_props]
        })
        logger.debug("Touch started")
        
        # Hold with micro-movements
        steps = int(duration * 5)
        step_duration = duration / steps
        
        for i in range(steps):
            finger_props["force"] = round(0.5 + random.uniform(0, 0.4), 3)
            finger_props["x"] = round(x + random.uniform(-1, 1), 2)
            finger_props["y"] = round(y + random.uniform(-1, 1), 2)
            
            cdp.send("Input.dispatchTouchEvent", {
                "type": "touchMove",
                "touchPoints": [finger_props]
            })
            time.sleep(step_duration)
        
        # Touch end
        cdp.send("Input.dispatchTouchEvent", {
            "type": "touchEnd",
            "touchPoints": []
        })
        
        cdp.detach()
        logger.info("✅ Mobile touch hold completed")
        return True
        
    except Exception as e:
        logger.error(f"Mobile touch hold failed: {e}")
        if cdp:
            try:
                cdp.send("Input.dispatchTouchEvent", {"type": "touchEnd", "touchPoints": []})
                cdp.detach()
            except:
                pass
        return False


def _desktop_mouse_hold(page, x: float, y: float, duration: float) -> bool:
    """Perform a long mouse hold using CDP mouse events."""
    cdp = None
    try:
        logger.debug(f"🖱️ Desktop mouse hold at ({x:.0f}, {y:.0f})")
        
        cdp = page.context.new_cdp_session(page)
        
        # Move to position
        cdp.send("Input.dispatchMouseEvent", {
            "type": "mouseMoved",
            "x": int(x),
            "y": int(y),
        })
        time.sleep(0.1)
        
        # Mouse down
        cdp.send("Input.dispatchMouseEvent", {
            "type": "mousePressed",
            "x": int(x),
            "y": int(y),
            "button": "left",
            "clickCount": 1,
        })
        logger.debug("Mouse pressed")
        
        # Hold with micro-movements
        steps = int(duration * 5)
        step_duration = duration / steps
        
        for i in range(steps):
            cdp.send("Input.dispatchMouseEvent", {
                "type": "mouseMoved",
                "x": int(x + random.uniform(-1, 1)),
                "y": int(y + random.uniform(-1, 1)),
                "button": "left",
            })
            time.sleep(step_duration)
        
        # Mouse up
        cdp.send("Input.dispatchMouseEvent", {
            "type": "mouseReleased",
            "x": int(x),
            "y": int(y),
            "button": "left",
            "clickCount": 1,
        })
        
        cdp.detach()
        logger.info("✅ Desktop mouse hold completed")
        return True
        
    except Exception as e:
        logger.error(f"Desktop mouse hold failed: {e}")
        if cdp:
            try:
                cdp.send("Input.dispatchMouseEvent", {
                    "type": "mouseReleased", "x": int(x), "y": int(y),
                    "button": "left", "clickCount": 1,
                })
                cdp.detach()
            except:
                pass
        return False


def _check_captcha_success(page) -> bool:
    """Check if CAPTCHA was solved successfully."""
    logger.debug("Checking CAPTCHA result...")
    time.sleep(3)
    
    # Check URL changed to privacy notice
    try:
        if "privacynotice" in page.url.lower():
            logger.info("✅ CAPTCHA solved - redirected to privacy notice")
            return True
    except:
        pass
    
    # Check if Press and hold is gone
    try:
        visible = False
        for frame in page.frames:
            try:
                if frame.locator(":text('Press and hold')").first.is_visible(timeout=1000):
                    visible = True
                    break
            except:
                continue
        
        if not visible:
            logger.info("✅ CAPTCHA appears solved (button no longer visible)")
            return True
    except:
        pass
    
    logger.debug("CAPTCHA status unclear, assuming success")
    return True
