import random
import sys
import time
from typing import Literal
from playwright.sync_api import Locator, Page, Keyboard
from utils.mouse_random_click import human_like_mouse_click

from loguru import logger

IS_MAC = sys.platform == "darwin"

# === Default Parameters (for "manual" mode) ===

# --- Base Speed and Typing Style ---
KEY_PRESS_DELAY_RANGE = (0.04, 0.12)  # Delay range (in sec) between keystrokes. Foundation of typing speed.
# Decrease: faster typing. Increase: slower, "thoughtful" typing.
KEY_DOWN_DURATION_RANGE = (0.01, 0.04)  # Duration of each key press.

# --- "Humanization" of Typing Process ---
MISTAKE_PROBABILITY = 0.1  # Probability (0.0 to 1.0) of making a mistake per character.
# 0.0 disables mistakes. 0.03 = 3% chance of error.
MISTAKE_CORRECTION_DELAY_RANGE = (0.1, 0.4)  # Pause (in sec) after making a mistake, before pressing Backspace.
BACKSPACE_DELAY_RANGE = (0.05, 0.15)  # Pause (in sec) AFTER pressing Backspace, before typing the correct character.
DOUBLE_CHAR_PROBABILITY = 0.01  # Probability of accidental double press.

# --- Pauses During Typing ---
WORD_PAUSE_PROBABILITY = 0.10  # Probability (0.0 to 1.0) of a short pause after a space (between words).
WORD_PAUSE_DURATION_RANGE = (0.1, 0.5)  # Duration (in sec) of a short pause between words.
LONG_PAUSE_PROBABILITY = 0.01  # Probability (0.0 to 1.0) of a long "thoughtful" pause during typing.
LONG_PAUSE_DURATION_RANGE = (0.8, 2.5)  # Duration (in sec) of a long pause.

# --- Chunking ---
# Simulates typing several characters in a row and a short pause before the next batch.
ENABLE_CHUNK_TYPING = True  # True: use "chunk" typing. False: monotonous typing 1 character at a time.
CHUNK_SIZE_RANGE = (2, 7)  # Range (min, max) of characters in one chunk.
CHUNK_DELAY_RANGE = (0.08, 0.25)  # Pause (in sec) between chunks of characters.

# --- Preset Typing Speed Profiles (can be modified) ---
TYPING_PROFILES = {
    "fast": {
        "KEY_PRESS_DELAY_RANGE": (0.01, 0.05),
        "KEY_DOWN_DURATION_RANGE": (0.008, 0.025),
        "MISTAKE_PROBABILITY": 0.01,
        "DOUBLE_CHAR_PROBABILITY": 0.005,
        "MISTAKE_CORRECTION_DELAY_RANGE": (0.05, 0.15),
        "BACKSPACE_DELAY_RANGE": (0.03, 0.08),
        "WORD_PAUSE_PROBABILITY": 0.05,
        "WORD_PAUSE_DURATION_RANGE": (0.05, 0.2),
        "LONG_PAUSE_PROBABILITY": 0.005,
        "LONG_PAUSE_DURATION_RANGE": (0.4, 1.0),
        "ENABLE_CHUNK_TYPING": True,
        "CHUNK_SIZE_RANGE": (4, 10),
        "CHUNK_DELAY_RANGE": (0.06, 0.15),
    },
    "medium": {
        "KEY_PRESS_DELAY_RANGE": (0.03, 0.11),
        "KEY_DOWN_DURATION_RANGE": (0.01, 0.04),
        "MISTAKE_PROBABILITY": 0.04,
        "DOUBLE_CHAR_PROBABILITY": 0.01,
        "MISTAKE_CORRECTION_DELAY_RANGE": (0.1, 0.4),
        "BACKSPACE_DELAY_RANGE": (0.05, 0.15),
        "WORD_PAUSE_PROBABILITY": 0.10,
        "WORD_PAUSE_DURATION_RANGE": (0.1, 0.5),
        "LONG_PAUSE_PROBABILITY": 0.01,
        "LONG_PAUSE_DURATION_RANGE": (0.8, 2.5),
        "ENABLE_CHUNK_TYPING": True,
        "CHUNK_SIZE_RANGE": (2, 7),
        "CHUNK_DELAY_RANGE": (0.08, 0.25),
    },
    "slow": {
        "KEY_PRESS_DELAY_RANGE": (0.08, 0.22),
        "KEY_DOWN_DURATION_RANGE": (0.04, 0.09),
        "MISTAKE_PROBABILITY": 0.08,
        "DOUBLE_CHAR_PROBABILITY": 0.02,
        "MISTAKE_CORRECTION_DELAY_RANGE": (0.3, 0.8),
        "BACKSPACE_DELAY_RANGE": (0.1, 0.3),
        "WORD_PAUSE_PROBABILITY": 0.18,
        "WORD_PAUSE_DURATION_RANGE": (0.4, 1.2),
        "LONG_PAUSE_PROBABILITY": 0.03,
        "LONG_PAUSE_DURATION_RANGE": (1.5, 4.0),
        "ENABLE_CHUNK_TYPING": False,
        "CHUNK_SIZE_RANGE": (1, 1),
        "CHUNK_DELAY_RANGE": (0.0, 0.0),
    },
    "paste": {
        "PASTE_DELAY_RANGE": (0.2, 0.6)
    }
}

NEIGHBORING_KEYS = {
    'q': 'wsa', 'w': 'qase', 'e': 'wsdr', 'r': 'edft', 't': 'rfgy', 'y': 'tghu', 'u': 'yhji',
    'i': 'ujko', 'o': 'iklp', 'p': 'ol', 'a': 'qwsz', 's': 'qwedcxza', 'd': 'werfvcxs',
    'f': 'ertgbvcd', 'g': 'rtyhnbvf', 'h': 'tyujmnbg', 'j': 'uikmnh', 'k': 'iolmj',
    'l': 'opk', 'z': 'asx', 'x': 'zsdc', 'c': 'xdfv', 'v': 'cfgb', 'b': 'vghn', 'n': 'bghjm', 'm': 'nhjk',
}
SHIFT_MAP = {
    '!': '1', '@': '2', '#': '3', '$': '4', '%': '5', '^': '6', '&': '7', '*': '8', '(': '9', ')': '0',
    '_': '-', '+': '=',
    '{': '[', '}': ']',
    '|': '\\', '?': '/',
    ':': ';', '"': "'",
    '<': ',', '>': '.',
}


def _press_key_humanly(keyboard: Keyboard, key: str, duration_range: tuple):
    keyboard.down(key)
    time.sleep(random.uniform(*duration_range))
    keyboard.up(key)


def human_like_hotkey(keyboard, main_key, modifier="Control", down_delay=(0.02, 0.08), up_delay=(0.01, 0.06)):
    keyboard.down(modifier)
    time.sleep(random.uniform(*down_delay))
    keyboard.down(main_key)
    time.sleep(random.uniform(*down_delay))
    keyboard.up(main_key)
    time.sleep(random.uniform(*up_delay))
    keyboard.up(modifier)
    time.sleep(random.uniform(*up_delay))


def human_like_type(
        locator: Locator,
        text_to_type: str,
        speed_mode: Literal["fast", "medium", "slow", "manual"] = "paste",
        clear_before: bool = True,
        focus_with_click: bool = True
) -> bool:
    page: Page = locator.page
    logger.info(f"Typing '{text_to_type[:30]}...' into locator. Mode: {speed_mode}")

    modifier_key = "Meta" if IS_MAC else "Control"

    if speed_mode == "paste":
        try:
            locator.wait_for(state="visible", timeout=10000)
            if focus_with_click:
                locator.click()
            else:
                locator.focus()

            if clear_before:
                human_like_hotkey(page.keyboard, "A", modifier_key)
                time.sleep(random.uniform(0.06, 0.15))
                _press_key_humanly(page.keyboard, "Backspace", (0.04, 0.12))
                time.sleep(random.uniform(0.07, 0.15))

            logger.info("Simulating paste from clipboard.")
            page.evaluate("text => navigator.clipboard.writeText(text)", text_to_type)
            time.sleep(random.uniform(*TYPING_PROFILES["paste"]["PASTE_DELAY_RANGE"]))
            human_like_hotkey(page.keyboard, "V", modifier_key)
            logger.success("Successfully pasted text.")
            return True
        except Exception as e:
            logger.error(f"Error during paste operation: {e}")
            return False


    if speed_mode == "manual":
        current_params = {
            "KEY_PRESS_DELAY_RANGE": KEY_PRESS_DELAY_RANGE, "KEY_DOWN_DURATION_RANGE": KEY_DOWN_DURATION_RANGE,
            "MISTAKE_PROBABILITY": MISTAKE_PROBABILITY, "DOUBLE_CHAR_PROBABILITY": DOUBLE_CHAR_PROBABILITY,
            "MISTAKE_CORRECTION_DELAY_RANGE": MISTAKE_CORRECTION_DELAY_RANGE,
            "BACKSPACE_DELAY_RANGE": BACKSPACE_DELAY_RANGE,
            "WORD_PAUSE_PROBABILITY": WORD_PAUSE_PROBABILITY, "WORD_PAUSE_DURATION_RANGE": WORD_PAUSE_DURATION_RANGE,
            "LONG_PAUSE_PROBABILITY": LONG_PAUSE_PROBABILITY, "LONG_PAUSE_DURATION_RANGE": LONG_PAUSE_DURATION_RANGE,
            "ENABLE_CHUNK_TYPING": ENABLE_CHUNK_TYPING, "CHUNK_SIZE_RANGE": CHUNK_SIZE_RANGE,
            "CHUNK_DELAY_RANGE": CHUNK_DELAY_RANGE
        }
    elif speed_mode in TYPING_PROFILES:
        logger.debug(f"Using '{speed_mode}' typing profile.")
        current_params = TYPING_PROFILES[speed_mode]
    else:
        logger.warning(f"Unknown typing speed_mode '{speed_mode}'. Defaulting to 'medium'.")
        current_params = TYPING_PROFILES["medium"]

    p_key_delay = current_params["KEY_PRESS_DELAY_RANGE"]
    p_mistake_prob = current_params["MISTAKE_PROBABILITY"]
    p_mistake_delay = current_params["MISTAKE_CORRECTION_DELAY_RANGE"]
    p_double_char_prob = current_params["DOUBLE_CHAR_PROBABILITY"]
    p_key_down_duration = current_params["KEY_DOWN_DURATION_RANGE"]
    p_backspace_delay = current_params["BACKSPACE_DELAY_RANGE"]
    p_word_pause_prob = current_params["WORD_PAUSE_PROBABILITY"]
    p_word_pause_dur = current_params["WORD_PAUSE_DURATION_RANGE"]
    p_long_pause_prob = current_params["LONG_PAUSE_PROBABILITY"]
    p_long_pause_dur = current_params["LONG_PAUSE_DURATION_RANGE"]
    p_chunk_typing = current_params["ENABLE_CHUNK_TYPING"]
    p_chunk_size = current_params["CHUNK_SIZE_RANGE"]
    p_chunk_delay = current_params["CHUNK_DELAY_RANGE"]

    try:
        locator.wait_for(state="visible", timeout=10000)

        if focus_with_click:
            human_like_mouse_click(locator)  # TODO replace with custom "human-like" click
        else:
            locator.focus()

        time.sleep(random.uniform(0.12, 0.20))

        if clear_before:
            keyboard = page.keyboard
            human_like_hotkey(keyboard, "A", modifier_key)
            time.sleep(random.uniform(0.04, 0.12))
            _press_key_humanly(keyboard, "Backspace", p_key_down_duration)
            time.sleep(random.uniform(0.1, 0.2))
        keyboard = page.keyboard
        text_len = len(text_to_type)
        cursor = 0
        while cursor < text_len:
            if p_chunk_typing:
                chunk_size = random.randint(*p_chunk_size)
                chunk = text_to_type[cursor: cursor + chunk_size]
            else:
                chunk = text_to_type[cursor: cursor + 1]

            for char in chunk:

                if random.random() < p_long_pause_prob:
                    time.sleep(random.uniform(*p_long_pause_dur))

                if random.random() < p_mistake_prob and char.lower() in NEIGHBORING_KEYS:
                    mistake_char = random.choice(NEIGHBORING_KEYS[char.lower()])
                    logger.trace(f"Making a mistake: typed '{mistake_char}' instead of '{char}'")
                    _press_key_humanly(keyboard, mistake_char, p_key_down_duration)
                    time.sleep(random.uniform(*p_mistake_delay))
                    _press_key_humanly(keyboard, "Backspace", p_key_down_duration)
                    time.sleep(random.uniform(*p_backspace_delay))

                # Check if character is typeable via keyboard.down()
                # Emojis and many special characters need insertText instead
                is_emoji = ord(char) > 127  # Basic check for non-ASCII
                is_upper = char.isupper()
                needs_shift = char in SHIFT_MAP

                if is_emoji:
                    # Use insertText for emojis and special unicode characters
                    keyboard.insert_text(char)
                elif needs_shift or is_upper:
                    keyboard.press(char)
                else:
                    _press_key_humanly(keyboard, char, p_key_down_duration)

                if random.random() < p_double_char_prob and char.isalpha():
                    logger.trace(f"Making a 'stuck key' mistake: typed '{char}' twice")
                    _press_key_humanly(keyboard, char, p_key_down_duration)
                    time.sleep(random.uniform(*p_mistake_delay))
                    _press_key_humanly(keyboard, "Backspace", p_key_down_duration)

                time.sleep(random.uniform(*p_key_delay))
                if char.isspace() and random.random() < p_word_pause_prob:
                    time.sleep(random.uniform(*p_word_pause_dur))

            cursor += len(chunk)
            if p_chunk_typing and cursor < text_len:
                time.sleep(random.uniform(*p_chunk_delay))

        logger.success(f"Successfully typed text into the locator.")
        return True

    except Exception as e:
        logger.error(f"Global error in human_like_type: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False
