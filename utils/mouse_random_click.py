import math
import random
import time
import pytweening as pt
from loguru import logger

DRAW_MODE = False

TIME_SLEEP_DEFAULT = 2.0 # Delay between clicks (if set to 2 seconds, random delay from 2 to 3 seconds)

# === Default Parameters (for "manual" mode) ===

# --- General Speed and Mouse Gesture Detail ---
STEP_BASE_DISTANCE = 30  # Base distance (in pixels) for one main mouse step.
# Decrease: more steps for the same distance = potentially smoother but slower (due to delays/ops per step).
# Increase: fewer steps = faster, but movement might appear "rougher".
STEP_RANDOMNESS = (0.8, 1.2)  # Random multiplier applied to the calculated number of steps.
# Narrowing range (e.g. (0.9, 1.1)) = more predictable step count.
# Widening range = greater variability in step count and thus speed.
STEP_MIN = 3  # Minimum number of steps for any mouse movement.
# Decrease (e.g. to 1-2) can speed up very short movements.
STEP_MAX = 7  # Maximum number of steps for any mouse movement.
# Decrease speeds up long movements but makes them less detailed.
# Increase allows long movements to be smoother (more anchor points for pytweening).
STEP_MAX_IF_NEAR = 3  # Maximum number of steps if current distance to target is less than CLOSE_DISTANCE.
# Allows making short "finishing" moves faster.
CLOSE_DISTANCE = 40  # Distance threshold (in pixels). If current distance to target < this, STEP_MAX_IF_NEAR is used.

# --- Mouse Movement Delays ---
MICRO_STEP_DELAY_RANGE = (
    0.002, 0.008)  # Random delay range (in seconds) AFTER each main micro-step (except the last).
# Decreasing these values directly speeds up the entire gesture.
# Increasing slows down the gesture, simulating more "thoughtfulness".
SMOOTH_MOVE_DELAY = (
    0.002, 0.008)  # Random delay range (in seconds) for each step of final trajectory "smoothing".
# Decrease speeds up the smoothing phase.

# --- "Humanization" Elements ---
SHIFT_OFFSET_BEFORE_CLICK_COUNT = (
    1, 3)  # Range (min, max) of very short "aiming" moves before clicking.
# Setting to (0,0) or (0,1) with low probability will disable or minimize this effect.
SHIFT_OFFSET_BEFORE_CLICK_RANGE = (-2, 2)  # Range (in pixels) for each "aiming" shift.
# Decreasing range makes "aiming" less noticeable.
JITTER_AMOUNT = 3  # Maximum random offset (in pixels) from "ideal" trajectory anchor point at each main step.
# Decrease (to 0-1) makes trajectory smoother. Increase adds "jitter".
ENABLE_SUB_STEP_CURVING = True  # True: curve each micro-segment of trajectory. False: micro-segments will be straight.
# Setting to False slightly speeds up the program.
SUB_STEP_CURVE_AMOUNT_MAX = 3  # Maximum deviation (in pixels) for curve point from straight line of micro-segment.
# Decrease: less pronounced curve.
SUB_STEP_SEGMENTS = 2  # Number of sub-segments to split each micro-segment into for curving (2 = 1 curve point).
# Decrease to 2 (if it was higher): faster. Increase > 2: slower, but curve is smoother.

# --- Scroll Parameters ---
SCROLL_CHUNK_SIZE_RANGE = (
    100, 250)  # Range (min, max) size of one scroll tick in pixels.
# Decrease: scroll will be smaller and more frequent "ticks" (slower, but smoother).
# Increase: scroll will be larger "jumps" (faster, but sharper).
SCROLL_CHUNK_DELAY_RANGE = (
    0.02, 0.07)  # Range (min_sec, max_sec) pause between individual scroll ticks.
# Decrease: faster, continuous scroll.
# Increase: slower, intermittent scroll.
SCROLL_LONG_PAUSE_PROBABILITY = 0.15  # Probability (0.0 to 1.0) of a "thoughtful" pause occurring during scroll process.
# Increase: more frequent long pauses. 0.0 to disable.
SCROLL_LONG_PAUSE_DURATION_RANGE = (0.4, 1.2)  # Range (min_sec, max_sec) duration of "thoughtful" pause.
SCROLL_MOUSE_WIGGLE_DURING_PAUSE = True  # True: wiggle mouse cursor slightly during scroll pauses.
# False: cursor will be valid during scroll pauses.
SCROLL_MOUSE_WIGGLE_AMOUNT = (
    5, 15)  # Range (min_px, max_px) of random cursor offset during scroll pauses.
SCROLL_PAUSE_AFTER_CHUNKS = (
    0.06, 0.15)  # Range (min_sec, max_sec) total pause AFTER executing a series of scroll "chunks",
# if long pause did not trigger.
SCROLL_JITTER_PER_CHUNK = (
    -20, 20)  # Range (min_px, max_px) random "jitter" added to size of EACH scroll "chunk".
REVERSE_SCROLL_PROBABILITY = 0.10  # Probability (0.0 to 1.0) that scroll will go in reverse direction.

# --- Pytweening Easing Functions ---
EASING_FUNCTIONS_ALL = [  # Full set for maximum variety of "human" modes
    pt.easeOutQuad, pt.easeInOutQuad, pt.easeOutCubic, pt.easeInOutCubic,
    pt.easeOutSine, pt.easeInOutSine, pt.easeOutExpo, pt.easeInOutExpo,
    pt.easeOutElastic, pt.easeInOutElastic, pt.easeOutBack, pt.easeInOutBack,
    pt.linear
]
EASING_FUNCTIONS_MEDIUM = [  # Set for "medium" humanity, without too exotic ones
    pt.easeOutQuad, pt.easeInOutQuad, pt.easeOutCubic, pt.easeInOutCubic,
    pt.easeOutSine, pt.easeInOutSine, pt.easeOutExpo, pt.easeInOutExpo, pt.linear
]

# --- Parameters for click itself and mouse "move away" after click ---
CLICK_PRESS_DURATION_RANGE = (0.05, 0.15)  # Range (min_sec, max_sec) time mouse button is "held".
# Decrease: faster, "sharper" click.
ENABLE_POST_CLICK_MOVE = True  # True: cursor will move slightly "away" after click. False: cursor stays at click place (faster).
POST_CLICK_MOVE_DISTANCE_RANGE = (25, 50)  # Range (min_px, max_px) distance cursor will "move away".
POST_CLICK_MOVE_DURATION_RANGE = (0.6, 1.2)  # Range (min_sec, max_sec) time for "move away" to happen.
# Decrease: faster move away.
POST_CLICK_MOVE_STEPS_RANGE = (5, 10)  # Number of steps for "move away" animation.
# Decrease: faster, but less smooth move away.
POST_CLICK_EASING_FUNCTIONS = [pt.easeOutSine, pt.easeOutQuad, pt.easeOutCubic, pt.easeOutExpo,
                               pt.easeOutBack]  # Easing functions for "move away".

_human_click_last_pos = None  # Do not touch, internal variable for tracking position

def reset_mouse_state():
    """
    Resets the internal state of the human mouse input.
    Call this when starting a new session or page to prevent 'teleportation' artifacts.
    """
    global _human_click_last_pos
    _human_click_last_pos = None

# --- Preset Parameter Sets ---
SPEED_PROFILES = {
    "fast": {
        "STEP_BASE_DISTANCE": 25, "STEP_RANDOMNESS": (0.7, 1.3), "STEP_MIN": 10, "STEP_MAX": 16,
        "STEP_MAX_IF_NEAR": 7, "CLOSE_DISTANCE": 50, "MICRO_STEP_DELAY_RANGE": (0.008, 0.020),
        "SMOOTH_MOVE_DELAY": (0.008, 0.020),
        "SHIFT_OFFSET_BEFORE_CLICK_COUNT": (1, 2), "SHIFT_OFFSET_BEFORE_CLICK_RANGE": (-3, 3),
        "JITTER_AMOUNT": 2, "ENABLE_SUB_STEP_CURVING": True,
        "SUB_STEP_CURVE_AMOUNT_MAX": 2, "SUB_STEP_SEGMENTS": 2,
        "EASING_FUNCTIONS": EASING_FUNCTIONS_MEDIUM,
        "CLICK_PRESS_DURATION_RANGE": (0.05, 0.15), "ENABLE_POST_CLICK_MOVE": True,
        "POST_CLICK_MOVE_DISTANCE_RANGE": (25, 70), "POST_CLICK_MOVE_DURATION_RANGE": (0.2, 0.5),
        "POST_CLICK_MOVE_STEPS_RANGE": (5, 10), "POST_CLICK_EASING_FUNCTIONS": POST_CLICK_EASING_FUNCTIONS
    },
    "medium": {
        "STEP_BASE_DISTANCE": 20, "STEP_RANDOMNESS": (0.6, 1.4), "STEP_MIN": 25, "STEP_MAX": 52,
        "STEP_MAX_IF_NEAR": 9, "CLOSE_DISTANCE": 60, "MICRO_STEP_DELAY_RANGE": (0.015, 0.040),
        "SMOOTH_MOVE_DELAY": (0.015, 0.035),
        "SHIFT_OFFSET_BEFORE_CLICK_COUNT": (2, 4), "SHIFT_OFFSET_BEFORE_CLICK_RANGE": (-4, 4),
        "JITTER_AMOUNT": 3, "ENABLE_SUB_STEP_CURVING": True,
        "SUB_STEP_CURVE_AMOUNT_MAX": 3, "SUB_STEP_SEGMENTS": 3,
        "EASING_FUNCTIONS": EASING_FUNCTIONS_ALL,
        "CLICK_PRESS_DURATION_RANGE": (0.07, 0.20), "ENABLE_POST_CLICK_MOVE": True,
        "POST_CLICK_MOVE_DISTANCE_RANGE": (30, 90), "POST_CLICK_MOVE_DURATION_RANGE": (0.3, 0.8),
        "POST_CLICK_MOVE_STEPS_RANGE": (7, 15), "POST_CLICK_EASING_FUNCTIONS": EASING_FUNCTIONS_ALL
    },
    "slow": {
        "STEP_BASE_DISTANCE": 15, "STEP_RANDOMNESS": (0.5, 1.6), "STEP_MIN": 56, "STEP_MAX": 95,
        "STEP_MAX_IF_NEAR": 11, "CLOSE_DISTANCE": 70, "MICRO_STEP_DELAY_RANGE": (0.025, 0.060),
        "SMOOTH_MOVE_DELAY": (0.025, 0.050),
        "SHIFT_OFFSET_BEFORE_CLICK_COUNT": (2, 5), "SHIFT_OFFSET_BEFORE_CLICK_RANGE": (-5, 5),
        "JITTER_AMOUNT": 5, "ENABLE_SUB_STEP_CURVING": True,
        "SUB_STEP_CURVE_AMOUNT_MAX": 4, "SUB_STEP_SEGMENTS": 4,
        "EASING_FUNCTIONS": EASING_FUNCTIONS_ALL,
        "CLICK_PRESS_DURATION_RANGE": (0.08, 0.25), "ENABLE_POST_CLICK_MOVE": True,
        "POST_CLICK_MOVE_DISTANCE_RANGE": (40, 120), "POST_CLICK_MOVE_DURATION_RANGE": (0.4, 1.2),
        "POST_CLICK_MOVE_STEPS_RANGE": (8, 20), "POST_CLICK_EASING_FUNCTIONS": EASING_FUNCTIONS_ALL
    }
}


def get_random_point_in_ellipse(width: float, height: float):
    cx = width / 2
    cy = height / 2
    rx = width / 2
    ry = height / 2
    u1 = random.uniform(0, 1)
    u2 = random.uniform(0, 1)
    rand_r_norm = math.sqrt(u1)
    rand_angle_norm = 2 * math.pi * u2
    x_norm = rand_r_norm * math.cos(rand_angle_norm)
    y_norm = rand_r_norm * math.sin(rand_angle_norm)
    rand_x_offset = cx + x_norm * rx
    rand_y_offset = cy + y_norm * ry
    return rand_x_offset, rand_y_offset

def get_viewport_size(page):
    vp = page.viewport_size
    if not vp:
        try:
            vp_js = page.evaluate("() => ({ width: window.innerWidth, height: window.innerHeight })")
            return {"width": vp_js["width"], "height": vp_js["height"]}
        except Exception as e:
            logger.warning(f"Fallback viewport detection via JS failed: {e}")
            return {"width": 1280, "height": 720}  # резервное значение
    return vp

def _do_tweened_move(page, start_x, start_y, end_x, end_y, duration_s, steps, ease_func):
    mouse = page.mouse
    current_x, current_y = start_x, start_y
    distance = math.dist((start_x, start_y), (end_x, end_y))
    if distance < 0.1:
        if round(start_x) != round(end_x) or round(start_y) != round(end_y):
            mouse.move(round(end_x), round(end_y))
            if DRAW_MODE: mouse.down()
        return end_x, end_y
    delay_per_step = duration_s / steps if steps > 0 else 0
    for i in range(steps):
        raw_progress = (i + 1) / steps
        eased_progress = ease_func(raw_progress)
        move_to_x = start_x + (end_x - start_x) * eased_progress
        move_to_y = start_y + (end_y - start_y) * eased_progress
        vp_s = get_viewport_size(page)
        if vp_s:
            move_to_x = max(0, min(move_to_x, vp_s['width'] - 1))
            move_to_y = max(0, min(move_to_y, vp_s['height'] - 1))
        mouse.move(round(move_to_x), round(move_to_y))
        if DRAW_MODE: mouse.down()

        current_x, current_y = move_to_x, move_to_y
        if i < steps - 1 and delay_per_step > 0.001:
            time.sleep(delay_per_step)
    if round(current_x) != round(end_x) or round(current_y) != round(end_y):
        mouse.move(round(end_x), round(end_y))
        if DRAW_MODE: mouse.down()

    return end_x, end_y


def human_like_mouse_click(locator, time_sleep: float = TIME_SLEEP_DEFAULT, speed_mode: str = "fast",
                           no_scroll: bool = False):
    page = locator.page
    global _human_click_last_pos

    current_params = {}
    if speed_mode == "manual":
        logger.debug("Using 'manual' speed profile (global defaults).")
        current_params = {
            "STEP_BASE_DISTANCE": STEP_BASE_DISTANCE, "STEP_RANDOMNESS": STEP_RANDOMNESS,
            "STEP_MIN": STEP_MIN, "STEP_MAX": STEP_MAX, "STEP_MAX_IF_NEAR": STEP_MAX_IF_NEAR,
            "CLOSE_DISTANCE": CLOSE_DISTANCE, "MICRO_STEP_DELAY_RANGE": MICRO_STEP_DELAY_RANGE,
            "SMOOTH_MOVE_DELAY": SMOOTH_MOVE_DELAY,
            "SHIFT_OFFSET_BEFORE_CLICK_COUNT": SHIFT_OFFSET_BEFORE_CLICK_COUNT,
            "SHIFT_OFFSET_BEFORE_CLICK_RANGE": SHIFT_OFFSET_BEFORE_CLICK_RANGE,
            "JITTER_AMOUNT": JITTER_AMOUNT, "ENABLE_SUB_STEP_CURVING": ENABLE_SUB_STEP_CURVING,
            "SUB_STEP_CURVE_AMOUNT_MAX": SUB_STEP_CURVE_AMOUNT_MAX, "SUB_STEP_SEGMENTS": SUB_STEP_SEGMENTS,
            "EASING_FUNCTIONS": EASING_FUNCTIONS_ALL, "CLICK_PRESS_DURATION_RANGE": CLICK_PRESS_DURATION_RANGE,
            "ENABLE_POST_CLICK_MOVE": ENABLE_POST_CLICK_MOVE,
            "POST_CLICK_MOVE_DISTANCE_RANGE": POST_CLICK_MOVE_DISTANCE_RANGE,
            "POST_CLICK_MOVE_DURATION_RANGE": POST_CLICK_MOVE_DURATION_RANGE,
            "POST_CLICK_MOVE_STEPS_RANGE": POST_CLICK_MOVE_STEPS_RANGE,
            "POST_CLICK_EASING_FUNCTIONS": POST_CLICK_EASING_FUNCTIONS
        }
    elif speed_mode in SPEED_PROFILES:
        logger.debug(f"Using '{speed_mode}' speed profile.")
        current_params = SPEED_PROFILES[speed_mode]
    else:
        logger.warning(f"Unknown speed_mode '{speed_mode}'. Defaulting to 'fast'.")
        current_params = SPEED_PROFILES["fast"]

    p_step_base_distance = current_params["STEP_BASE_DISTANCE"]
    p_step_randomness = current_params["STEP_RANDOMNESS"]
    p_step_min = current_params["STEP_MIN"]
    p_step_max = current_params["STEP_MAX"]
    p_step_max_if_near = current_params["STEP_MAX_IF_NEAR"]
    p_close_distance = current_params["CLOSE_DISTANCE"]
    p_micro_step_delay_range = current_params["MICRO_STEP_DELAY_RANGE"]
    p_smooth_move_delay = current_params["SMOOTH_MOVE_DELAY"]
    p_shift_offset_before_click_count = current_params["SHIFT_OFFSET_BEFORE_CLICK_COUNT"]
    p_shift_offset_before_click_range = current_params["SHIFT_OFFSET_BEFORE_CLICK_RANGE"]
    p_jitter_amount = current_params["JITTER_AMOUNT"]
    p_enable_sub_step_curving = current_params["ENABLE_SUB_STEP_CURVING"]
    p_sub_step_curve_amount_max = current_params["SUB_STEP_CURVE_AMOUNT_MAX"]
    p_sub_step_segments = current_params["SUB_STEP_SEGMENTS"]
    p_easing_functions = current_params["EASING_FUNCTIONS"]
    p_click_press_duration_range = current_params["CLICK_PRESS_DURATION_RANGE"]
    p_enable_post_click_move = current_params["ENABLE_POST_CLICK_MOVE"]
    p_post_click_move_distance_range = current_params["POST_CLICK_MOVE_DISTANCE_RANGE"]
    p_post_click_move_duration_range = current_params["POST_CLICK_MOVE_DURATION_RANGE"]
    p_post_click_move_steps_range = current_params["POST_CLICK_MOVE_STEPS_RANGE"]
    p_post_click_easing_functions = current_params["POST_CLICK_EASING_FUNCTIONS"]

    try:
        locator.wait_for(state="visible", timeout=10000)
    except Exception as e:
        logger.error(f"[human_like_mouse_click] Locator did not appear in time: {e}")
        return

                             
    initial_scroll_y = page.evaluate("() => window.scrollY")

    def scroll_to_element_humanly():
        nonlocal page, locator
        logger.debug(f"HumanScroll: Initiating for {locator}")
        viewport_height = page.evaluate("() => window.innerHeight")
        if not viewport_height: return False
        max_attempts = 25

        for attempt in range(max_attempts):
            element_info = None
            try:
                element_info = locator.bounding_box(timeout=300)
            except Exception as e_bb:
                logger.trace(f"HumanScroll: BBox not found attempt {attempt + 1}: {e_bb}")

            if element_info:
                el_y, el_h = element_info["y"], element_info["height"]
                vis_ratio = 0
                if el_y < viewport_height and el_y + el_h > 0:
                    vis_top = max(0, el_y)
                    vis_bot = min(viewport_height, el_y + el_h)
                    if el_h > 0: vis_ratio = (vis_bot - vis_top) / el_h
                if vis_ratio > 0.95:
                    logger.success(f"HumanScroll: Element fully visible. Ratio:{vis_ratio:.2f}")
                    return True

            if no_scroll:
                logger.debug("no_scroll is True, skipping scroll action.")
                return element_info is not None

            if element_info:
                if el_y + el_h / 2 < viewport_height * 0.4:
                    scroll_direction = -1
                elif el_y + el_h / 2 > viewport_height * 0.6:
                    scroll_direction = 1
                elif el_y < 0:
                    scroll_direction = -1
                else:
                    scroll_direction = 1
            else:
                scroll_direction = 1

            if random.random() < REVERSE_SCROLL_PROBABILITY and scroll_direction != 0:
                scroll_direction *= -1

            current_sy = page.evaluate("() => window.scrollY")
            doc_sh = max(page.evaluate("() => document.body.scrollHeight"),
                         page.evaluate("() => document.documentElement.scrollHeight"), viewport_height)
            at_bottom = scroll_direction > 0 and current_sy + viewport_height >= doc_sh - 5
            at_top = scroll_direction < 0 and current_sy <= 5

            if (at_bottom and scroll_direction > 0) or (at_top and scroll_direction < 0):
                final_check = None
                try:
                    final_check = locator.bounding_box(timeout=100)
                except:
                    pass
                if final_check and 0 <= final_check["y"] < viewport_height: return True
                return False

            target_scroll_delta = (element_info["y"] + element_info["height"] / 2) - (
                        viewport_height / 2) if element_info else viewport_height * 0.7 * scroll_direction
            target_scroll_delta = max(-1.5 * viewport_height, min(target_scroll_delta, 1.5 * viewport_height))

            num_chunks = 0
            while abs(target_scroll_delta) > 20 and num_chunks < 5:
                chunk_size_base = random.uniform(*SCROLL_CHUNK_SIZE_RANGE)
                chunk_size = min(chunk_size_base, abs(target_scroll_delta)) * (1 if target_scroll_delta > 0 else -1)
                chunk_size += random.uniform(*SCROLL_JITTER_PER_CHUNK)
                if chunk_size > 0:
                    chunk_size = min(chunk_size, doc_sh - (current_sy + viewport_height) - 5)
                else:
                    chunk_size = max(chunk_size, -current_sy + 5)
                if abs(chunk_size) < 10: break

                logger.trace(f"HumanScroll: Chunk scroll by {chunk_size:.0f}px")
                page.mouse.wheel(0, round(chunk_size))
                target_scroll_delta -= chunk_size;
                current_sy += chunk_size;
                num_chunks += 1
                time.sleep(random.uniform(*SCROLL_CHUNK_DELAY_RANGE))

                if SCROLL_MOUSE_WIGGLE_DURING_PAUSE and random.random() < 0.3:
                    vp_s_wiggle = get_viewport_size(page)
                    if vp_s_wiggle:
                        cx_wiggle, cy_wiggle = _human_click_last_pos if _human_click_last_pos else (
                        vp_s_wiggle['width'] / 2, vp_s_wiggle['height'] / 2)
                        wiggle_x = cx_wiggle + random.uniform(*SCROLL_MOUSE_WIGGLE_AMOUNT) * random.choice([-1, 1])
                        wiggle_y = cy_wiggle + random.uniform(*SCROLL_MOUSE_WIGGLE_AMOUNT) * random.choice([-1, 1])
                        _do_tweened_move(page, cx_wiggle, cy_wiggle, wiggle_x, wiggle_y, 0.1, 2, pt.easeOutSine)

            if num_chunks == 0 and abs(scroll_direction) > 0:
                page.mouse.wheel(0, round(min(viewport_height * 0.1, 50) * scroll_direction))
                time.sleep(random.uniform(*SCROLL_PAUSE_AFTER_CHUNKS))

            if random.random() < SCROLL_LONG_PAUSE_PROBABILITY:
                time.sleep(random.uniform(*SCROLL_LONG_PAUSE_DURATION_RANGE))
            elif num_chunks > 0:
                time.sleep(random.uniform(*SCROLL_PAUSE_AFTER_CHUNKS))

        logger.warning(f"HumanScroll: Max scroll attempts ({max_attempts}) reached for {locator}.")
        return False

    try:
        if not scroll_to_element_humanly():
            logger.error(f"Element {locator} not visible after scroll/check. Aborting.")
            return None

        curr_sy_after_scroll = page.evaluate("() => window.scrollY")
        if abs(curr_sy_after_scroll - initial_scroll_y) > 10:
            _human_click_last_pos = None

        box = None
        vp_s = None
        MAX_ATTEMPTS_BEFORE_CLICK = 3
        for attempt in range(MAX_ATTEMPTS_BEFORE_CLICK):
            try:
                box = locator.bounding_box(timeout=500)
                vp_s = get_viewport_size(page)
                if box and vp_s:
                    logger.trace(f"Got box and viewport on attempt {attempt + 1}")
                    break
                logger.warning(
                    f"Attempt {attempt + 1}/{MAX_ATTEMPTS_BEFORE_CLICK}: box={bool(box)}, viewport={bool(vp_s)}. Retrying...")
                time.sleep(0.5)
            except Exception as e:
                logger.warning(f"Exception on attempt {attempt + 1} to get box/viewport: {e}")
                time.sleep(0.5)

        if not box:
            logger.error(f"No bounding_box for {locator} after all attempts. Aborting.")
            return None
        if not vp_s:
            logger.error(f"Could not get viewport size after all attempts. Aborting.")
            return None

        logger.info(
            f"Clicking {locator}. Box:({box['x']:.0f},{box['y']:.0f} w:{box['width']:.0f},h:{box['height']:.0f}) Mode:{speed_mode}")
        mouse = page.mouse
        width, height = max(box["width"], 1), max(box["height"], 1)
        rand_x_el, rand_y_el = get_random_point_in_ellipse(width, height)
        end_x, end_y = box["x"] + rand_x_el, box["y"] + rand_y_el

        if _human_click_last_pos:
            start_x, start_y = _human_click_last_pos
        else:
            start_x, start_y = random.uniform(vp_s['width'] * 0.2, vp_s['width'] * 0.8), random.uniform(
                vp_s['height'] * 0.2, vp_s['height'] * 0.8)
            mouse.move(round(start_x), round(start_y))
            if DRAW_MODE: mouse.down()

        distance = math.dist((start_x, start_y), (end_x, end_y))
        s_factor = random.uniform(*p_step_randomness)
        steps = min(max(math.ceil(distance / p_step_base_distance * s_factor), p_step_min), p_step_max)
        if distance < p_close_distance and distance > 0.5:
            steps = min(steps, p_step_max_if_near)
        elif distance <= 0.5:
            steps = 1

        ease_func = random.choice(p_easing_functions)
        logger.trace(f"Ease:{ease_func.__name__}, Steps:{steps}, Dist:{distance:.0f}")
        current_x, current_y = start_x, start_y
        for i in range(steps):
            raw_prog = (i + 1) / steps
            eased_prog = ease_func(raw_prog)
            tgt_sup_x = start_x + (end_x - start_x) * eased_prog
            tgt_sup_y = start_y + (end_y - start_y) * eased_prog
            jit_x = random.uniform(-p_jitter_amount, p_jitter_amount) if distance > 1 else 0
            jit_y = random.uniform(-p_jitter_amount, p_jitter_amount) if distance > 1 else 0
            next_tgt_x = tgt_sup_x + jit_x
            next_tgt_y = tgt_sup_y + jit_y

            if p_enable_sub_step_curving and math.dist((current_x, current_y), (
            next_tgt_x, next_tgt_y)) > 1 and p_sub_step_segments > 1 and steps > 1:
                sub_sx, sub_sy = current_x, current_y;
                dx_s, dy_s = next_tgt_x - sub_sx, next_tgt_y - sub_sy
                n_x, n_y = -dy_s, dx_s;
                len_n = math.sqrt(n_x ** 2 + n_y ** 2)
                if len_n > 0: n_x /= len_n; n_y /= len_n
                curve_dir = 1 if random.random() < 0.5 else -1
                for k_sub in range(1, p_sub_step_segments + 1):
                    sub_p = k_sub / p_sub_step_segments
                    i_x = sub_sx + dx_s * sub_p;
                    i_y = sub_sy + dy_s * sub_p
                    curve_m = curve_dir * random.uniform(0.2, 0.6) * p_sub_step_curve_amount_max * math.sin(
                        math.pi * sub_p)
                    cvd_x, cvd_y = i_x + n_x * curve_m, i_y + n_y * curve_m
                    cvd_x = max(0, min(cvd_x, vp_s['width'] - 1));
                    cvd_y = max(0, min(cvd_y, vp_s['height'] - 1))
                    mouse.move(round(cvd_x), round(cvd_y))
                    if DRAW_MODE: mouse.down()
                    current_x, current_y = cvd_x, cvd_y
            else:
                next_tgt_x = max(0, min(next_tgt_x, vp_s['width'] - 1));
                next_tgt_y = max(0, min(next_tgt_y, vp_s['height'] - 1))
                mouse.move(round(next_tgt_x), round(next_tgt_y))
                if DRAW_MODE: mouse.down()
                current_x, current_y = next_tgt_x, next_tgt_y

            if i < steps - 1 and p_micro_step_delay_range[1] > 0:
                time.sleep(random.uniform(*p_micro_step_delay_range))

        if distance > 10 and steps > 1 and p_smooth_move_delay[1] > 0:
            for j_sm in range(2):
                sm_prog = (j_sm + 1) / 2
                fin_x = current_x + (end_x - current_x) * sm_prog;
                fin_y = current_y + (end_y - current_y) * sm_prog
                fin_x = max(0, min(fin_x, vp_s['width'] - 1));
                fin_y = max(0, min(fin_y, vp_s['height'] - 1))
                mouse.move(round(fin_x), round(fin_y))
                if DRAW_MODE: mouse.down()
                if j_sm < 1: time.sleep(random.uniform(*p_smooth_move_delay))
                current_x, current_y = fin_x, fin_y
        elif abs(current_x - end_x) > 0.5 or abs(current_y - end_y) > 0.5:
            mouse.move(round(end_x), round(end_y))
            if DRAW_MODE: mouse.down()
            current_x, current_y = end_x, end_y

        num_pre_click_shifts = random.randint(*p_shift_offset_before_click_count)
        if num_pre_click_shifts > 0 and (p_shift_offset_before_click_range[1] != p_shift_offset_before_click_range[0]):
            logger.trace(f"Performing {num_pre_click_shifts} pre-click aim-shifts.")
            for _ in range(num_pre_click_shifts):
                s_off_r = p_shift_offset_before_click_range
                sh_x = current_x + random.uniform(*s_off_r);
                sh_y = current_y + random.uniform(*s_off_r)
                sh_x = max(box["x"], min(sh_x, box["x"] + width - 1));
                sh_y = max(box["y"], min(sh_y, box["y"] + height - 1))
                sh_x = max(0, min(sh_x, vp_s['width'] - 1));
                sh_y = max(0, min(sh_y, vp_s['height'] - 1))
                if round(sh_x) != round(current_x) or round(sh_y) != round(current_y):
                    _do_tweened_move(page, current_x, current_y, sh_x, sh_y, random.uniform(0.01, 0.03),
                                     random.randint(1, 2), pt.easeOutSine)
                current_x, current_y = sh_x, sh_y
                if num_pre_click_shifts > 1 and _ < num_pre_click_shifts - 1:
                    time.sleep(random.uniform(0.01, 0.05))

        mouse.down()
        time.sleep(random.uniform(*p_click_press_duration_range))
        mouse.up()
        if DRAW_MODE: mouse.down()

        _human_click_last_pos = (current_x, current_y)
        logger.info(f"Click: ({current_x:.1f},{current_y:.1f}) on {locator}")
        time.sleep(random.uniform(time_sleep, time_sleep + 1.0))

        if p_enable_post_click_move:
            angle = random.uniform(0, 2 * math.pi)
            dist_mv = random.uniform(*p_post_click_move_distance_range)
            post_tgt_x = current_x + dist_mv * math.cos(angle);
            post_tgt_y = current_y + dist_mv * math.sin(angle)
            post_tgt_x = max(0, min(post_tgt_x, vp_s['width'] - 1));
            post_tgt_y = max(0, min(post_tgt_y, vp_s['height'] - 1))
            post_dur = random.uniform(*p_post_click_move_duration_range);
            post_steps = random.randint(*p_post_click_move_steps_range)
            post_ease = random.choice(p_post_click_easing_functions)
            fin_pos_x, fin_pos_y = _do_tweened_move(page, current_x, current_y, post_tgt_x, post_tgt_y, post_dur,
                                                    post_steps, post_ease)
            _human_click_last_pos = (fin_pos_x, fin_pos_y)

        return _human_click_last_pos

    except Exception as e:
        logger.error(f"Global error in human_like_mouse_click for {locator}: {e}")
        import traceback
        logger.error(traceback.format_exc())
        try:
            page.mouse.up()
            time.sleep(random.uniform(time_sleep, time_sleep + 1))
        except Exception:
            pass
        _human_click_last_pos = None
        return None
