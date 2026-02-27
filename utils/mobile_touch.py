import math
import random
import time
import pytweening as pt
from loguru import logger

# === Mobile "Fuzzy Finger" Parameters ===
FINGER_RADIUS_RANGE = (8.0, 18.0)
PRESSURE_RANGE = (0.35, 0.95)
TAP_DURATION_RANGE = (0.06, 0.12)

# Biomechanical Consistency
BASE_FINGER_ANGLE = 45.0  
ANGLE_VARIANCE = 15.0     

# Typing Parameters
KEY_PRESS_DELAY_RANGE = (0.05, 0.20) 
MISTAKE_PROBABILITY = 0.06 
NEIGHBORING_KEYS = {
    'q': 'wsa', 'w': 'qase', 'e': 'wsdr', 'r': 'edft', 't': 'rfgy', 'y': 'tghu', 'u': 'yhji',
    'i': 'ujko', 'o': 'iklp', 'p': 'ol', 'a': 'qwsz', 's': 'qwedcxza', 'd': 'werfvcxs',
    'f': 'ertgbvcd', 'g': 'rtyhnbvf', 'h': 'tyujmnbg', 'j': 'uikmnh', 'k': 'iolmj',
    'l': 'opk', 'z': 'asx', 'x': 'zsdc', 'c': 'xdfv', 'v': 'cfgb', 'b': 'vghn', 'n': 'bghjm', 'm': 'nhjk',
}

# Global counter for Touch IDs
_CURRENT_TOUCH_ID = 1

def _get_next_touch_id():
    global _CURRENT_TOUCH_ID
    tid = _CURRENT_TOUCH_ID
    _CURRENT_TOUCH_ID = 1 if _CURRENT_TOUCH_ID >= 9 else _CURRENT_TOUCH_ID + 1
    return tid

def get_fuzzy_touch_params(consistency_seed=None):
    if consistency_seed:
        random.seed(consistency_seed)
        
    radius_base = random.uniform(*FINGER_RADIUS_RANGE)
    angle = random.gauss(BASE_FINGER_ANGLE, ANGLE_VARIANCE)
    angle = max(0, min(90, angle))
    
    # Initial Force
    force = random.uniform(*PRESSURE_RANGE)
    
    # Calculate initial squish
    radius_x = radius_base * (0.8 + (force * 0.2))
    radius_y = radius_x * random.uniform(0.9, 1.1)

    return {
        "radiusX": round(radius_x, 2),
        "radiusY": round(radius_y, 2),
        "force": round(force, 3),
        "rotationAngle": round(angle, 1),
        "id": _get_next_touch_id(),
        "_base_radius": radius_base # Hidden storage for calculations
    }

def update_finger_physics(finger_props, new_force=None, angle_drift=0):
    """
    Central physics engine: Updates Force, Angle, and recalculates Radius
    to ensure physical consistency (The Squish Effect).
    """
    if new_force is not None:
        finger_props['force'] = max(0.1, min(1.0, new_force))
    
    if angle_drift != 0:
        finger_props['rotationAngle'] += angle_drift
        
    # Recalculate Radius based on current Force
    # Logic: Lower force = Smaller contact area
    base = finger_props.get("_base_radius", 10.0)
    squish_factor = 0.8 + (finger_props['force'] * 0.2)
    
    finger_props['radiusX'] = round(base * squish_factor, 2)
    # radiusY maintains its original aspect ratio roughly
    finger_props['radiusY'] = round(base * squish_factor * 1.05, 2)
    finger_props['force'] = round(finger_props['force'], 3)
    finger_props['rotationAngle'] = round(finger_props['rotationAngle'], 1)
    
    return finger_props

def interpolate_points_arc(p1, p2, steps, curve_magnitude=50, easing_func=pt.easeOutQuad):
    """
    Generates points along a curve with VELOCITY EASING.
    easing_func: Controls the speed (e.g. flick starts fast, ends slow).
    """
    path = []
    x1, y1 = p1
    x2, y2 = p2
    
    # Calculate control point
    cx = (x1 + x2) / 2 + int(curve_magnitude) 
    cy = (y1 + y2) / 2
    
    for i in range(steps):
        # Apply Easing to time 't'
        # linear t: 0.1, 0.2, 0.3 (Constant speed)
        # eased t:  0.3, 0.5, 0.8 (Fast start, slow end)
        progress = i / steps
        t = easing_func(progress)
        
        # Quadratic Bezier with eased t
        xt = (1-t)**2 * x1 + 2*(1-t)*t * cx + t**2 * x2
        yt = (1-t)**2 * y1 + 2*(1-t)*t * cy + t**2 * y2
        
        # Micro-Wobble
        jitter_x = random.uniform(-1.0, 1.0)
        jitter_y = random.uniform(-1.0, 1.0)
        
        path.append((xt + jitter_x, yt + jitter_y))
        
    return path

def human_like_mobile_tap(page, locator):
    cdp = None
    try:
        # 0. Safety Check
        if page.is_closed():
            logger.error("Page closed before tap.")
            return False

        locator.scroll_into_view_if_needed() # Ensure element is in viewport (User Check #2)
        locator.wait_for(state="visible", timeout=5000)
        box = locator.bounding_box()
        if not box: return False

        target_x = box['x'] + (box['width'] / 2) + random.gauss(0, box['width'] / 10)
        target_y = box['y'] + (box['height'] / 2) + random.gauss(0, box['height'] / 10)
        target_x = max(box['x'], min(target_x, box['x'] + box['width']))
        target_y = max(box['y'], min(target_y, box['y'] + box['height']))

        cdp = page.context.new_cdp_session(page)
        finger_props = get_fuzzy_touch_params()

        # 1. Touch Start
        cdp.send("Input.dispatchTouchEvent", {
            "type": "touchStart",
            "touchPoints": [{"x": round(target_x, 2), "y": round(target_y, 2), **finger_props}]
        })

        # 2. Micro-Slide
        steps = random.randint(2, 4)
        hold_time = random.uniform(*TAP_DURATION_RANGE)
        
        slide_x_dest = target_x + random.uniform(-2, 2)
        slide_y_dest = target_y + random.uniform(-2, 2)
        
        for i in range(steps):
            t = (i + 1) / steps
            curr_x = target_x + (slide_x_dest - target_x) * t
            curr_y = target_y + (slide_y_dest - target_y) * t
            
            # Physics: Slight pressure fluctuation during hold
            new_force = finger_props['force'] + random.uniform(-0.02, 0.02)
            update_finger_physics(finger_props, new_force=new_force)
            
            cdp.send("Input.dispatchTouchEvent", {
                "type": "touchMove",
                "touchPoints": [{"x": round(curr_x, 2), "y": round(curr_y, 2), **finger_props}]
            })
            time.sleep(hold_time / steps)

        return True

    except Exception as e:
        logger.error(f"Mobile Tap Failed: {e}")
        return False
        
    finally:
        if cdp:
            try:
                cdp.send("Input.dispatchTouchEvent", {"type": "touchEnd", "touchPoints": []})
                cdp.detach()
            except Exception: pass
        time.sleep(random.uniform(0.2, 0.5))

def human_like_mobile_scroll(page, direction="down", magnitude="medium"):
    cdp = None
    try:
        # 0. Safety Check
        if page.is_closed():
            logger.error("Page closed before scroll.")
            return

        # Viewport Logic
        vp = page.viewport_size
        if not vp:
            dim = page.evaluate("() => ({width: window.innerWidth, height: window.innerHeight})")
            width, height = dim['width'], dim['height']
        else:
            width, height = vp['width'], vp['height']

        # Coordinates
        start_x = width * random.uniform(0.3, 0.7) 
        start_y = height * random.uniform(0.6, 0.8) 
        dist_px = height * (0.5 if magnitude == "medium" else 0.25)
        dist_px += random.uniform(-50, 50)
        end_y = start_y - dist_px if direction == "down" else start_y + dist_px
        end_x = start_x + random.randint(-40, 40)

        # Velocity Calc
        distance_total = math.sqrt((end_x - start_x)**2 + (end_y - start_y)**2)
        target_velocity = random.uniform(1.8, 3.2)
        total_time_ms = distance_total / target_velocity
        frame_time_s = 0.016 
        steps = int((total_time_ms / 1000) / frame_time_s)
        steps = max(6, min(steps, 60))

        cdp = page.context.new_cdp_session(page)
        finger_props = get_fuzzy_touch_params()

        # 1. Touch Start
        cdp.send("Input.dispatchTouchEvent", {
            "type": "touchStart",
            "touchPoints": [{"x": round(start_x, 2), "y": round(start_y, 2), **finger_props}]
        })
        
        # 2. Movement (Bio-Mechanical Arc + Velocity Easing)
        raw_mag = random.randint(30, 80)
        # Right-hand bias: Curve direction depends on start X
        curve_mag = -raw_mag if start_x > width / 2 else raw_mag
        if random.random() < 0.10: curve_mag *= -1

        # Use easeOutCubic for realistic flick momentum
        path_points = interpolate_points_arc(
            (start_x, start_y), 
            (end_x, end_y), 
            steps, 
            curve_magnitude=curve_mag,
            easing_func=pt.easeOutCubic 
        )
        
        for i, (curr_x, curr_y) in enumerate(path_points):
            # Physics: Decay force (Lift off)
            new_force = finger_props['force'] * 0.95
            
            # Physics: Rotation Drift (Thumb joint rotation)
            drift = 0.5 if direction == "down" else -0.5
            
            update_finger_physics(finger_props, new_force=new_force, angle_drift=drift)
            
            cdp.send("Input.dispatchTouchEvent", {
                "type": "touchMove",
                "touchPoints": [{"x": round(curr_x, 2), "y": round(curr_y, 2), **finger_props}]
            })
            time.sleep(frame_time_s)

        # 3. Touch End (Immediate Lift)
        cdp.send("Input.dispatchTouchEvent", {"type": "touchEnd", "touchPoints": []})
        cdp.detach()
        
        time.sleep(random.uniform(1.2, 2.8)) 

    except Exception as e:
        logger.error(f"Mobile Scroll Failed: {e}")
        
    finally:
        if cdp:
            try: cdp.detach() 
            except: pass

def get_char_type(char):
    """Helper to determine the keyboard layer of a character."""
    if char.isalpha() or char == " ":
        return "alpha"
    if char.isdigit():
        return "numeric"
    return "symbol"

def human_like_mobile_type(locator, text):
    """
    Mobile typing with Mistake Simulation, Shift Penalty, AND Layout Switching penalties.
    Ensures element is focused before typing.
    """
    # 0. Check if ALREADY focused (Optimization)
    try:
        if locator.evaluate("el => document.activeElement === el"):
            logger.debug("Element already focused, skipping tap")
            # Just ensure viewport visibility without tapping
            locator.scroll_into_view_if_needed()
            time.sleep(0.2)
        else:
            # 1. Try to tap to focus
            # Initial attempt with fuzzy tap
            if not human_like_mobile_tap(locator.page, locator):
                logger.warning("Human-like tap failed, falling back to standard click")
                locator.click(force=True)
    except Exception as e:
        logger.warning(f"Focus/Tap exception: {e}")
        locator.click(force=True)

    # 2. Verify Focus & Retry
    try:
        # Check if focused
        is_focused = locator.evaluate("el => document.activeElement === el")
        
        if not is_focused:
            logger.info("Element not focused after tap, retrying with JS focus...")
            
            # Use JS to focus directly
            locator.evaluate("el => el.focus()")
            time.sleep(0.2)
            
            # Double check
            is_focused = locator.evaluate("el => document.activeElement === el")
            if not is_focused:
                logger.warning("JS focus failed, trying force click...")
                locator.click(force=True)
                time.sleep(0.2)
                
    except Exception as e:
        logger.warning(f"Focus check failed: {e}")


    # Wait for keyboard animation
    time.sleep(random.uniform(0.5, 1.0)) 
    
    keyboard = locator.page.keyboard
    current_layer = "alpha" # Phones default to alpha layer on focus
    
    for char in text:
        target_layer = get_char_type(char)
        
        # === 1. Layout Switching Penalty ===
        if target_layer != current_layer:
            # Simulate time to find and tap the "?123" or "ABC" button
            # This is usually slower than a normal keystroke
            logger.trace(f"Switching keyboard layer: {current_layer} -> {target_layer}")
            time.sleep(random.uniform(0.3, 0.6))
            current_layer = target_layer
            
        # === 2. Mistake Logic (Stays same) ===
        if random.random() < MISTAKE_PROBABILITY and char.lower() in NEIGHBORING_KEYS:
            mistake_char = random.choice(NEIGHBORING_KEYS[char.lower()])
            keyboard.type(mistake_char)
            time.sleep(random.uniform(0.15, 0.4)) 
            keyboard.press("Backspace")
            time.sleep(random.uniform(0.1, 0.2))
            
        # === 3. Shift Key Penalty ===
        if char.isupper():
            time.sleep(random.uniform(0.1, 0.3)) 
            
        # === 4. Type the Character ===
        keyboard.type(char)
        
        # === 5. Dynamic Delays ===
        if char == " ":
            # Spacebar is big and easy to hit
            time.sleep(random.uniform(0.10, 0.20))
        elif target_layer == "symbol":
            # Symbols take slightly longer to find visually
            time.sleep(random.uniform(0.15, 0.35))
        else:
            time.sleep(random.uniform(*KEY_PRESS_DELAY_RANGE)) 
    
    time.sleep(random.uniform(0.3, 0.7))
    # locator.press("Enter") 
    
    return True


