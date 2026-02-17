"""
Amazon Automation Configuration

Contains constants, product categories, timing delays, and retry settings.
"""

import random

# === Base URLs ===
AMAZON_BASE_URL = "https://www.amazon.com"
AMAZON_SEARCH_URL = f"{AMAZON_BASE_URL}/s"

# === Product Categories ===
# Electronic devices, books, gadgets for search

AUDIO_PRODUCTS = [
    "bluetooth speaker",
    "wireless earbuds",
    "portable speaker",
    "computer speakers",
    "gaming headset",
    "noise cancelling earbuds",
]

PERIPHERALS = [
    "wireless mouse",
    "gaming mouse",
    "ergonomic mouse",
    "bluetooth keyboard",
    "mechanical keyboard",
    "keyboard and mouse combo",
]

ACCESSORIES = [
    "usb hub",
    "laptop stand",
    "monitor stand",
    "mouse pad",
    "cable organizer",
    "laptop cooling pad",
]

MOBILE_ACCESSORIES = [
    "phone stand",
    "phone charger",
    "wireless charger",
    "power bank",
    "usb c cable",
    "phone tripod",
]

BOOKS = [
    "bestseller fiction",
    "science fiction book",
    "self help book",
    "programming book python",
    "fantasy novel",
    "mystery thriller book",
]

SMART_HOME = [
    "smart plug",
    "led strip lights",
    "smart bulb",
    "wifi outlet",
    "motion sensor light",
    "bluetooth tracker",
]

# Combined product list
ALL_PRODUCTS = (
    AUDIO_PRODUCTS +
    PERIPHERALS +
    ACCESSORIES +
    MOBILE_ACCESSORIES +
    BOOKS +
    SMART_HOME
)


def get_random_product() -> str:
    """Get a random product search term."""
    return random.choice(ALL_PRODUCTS)


def get_random_from_category(category: str) -> str:
    """Get random product from specific category."""
    categories = {
        "audio": AUDIO_PRODUCTS,
        "peripherals": PERIPHERALS,
        "accessories": ACCESSORIES,
        "mobile": MOBILE_ACCESSORIES,
        "books": BOOKS,
        "smart_home": SMART_HOME,
    }
    return random.choice(categories.get(category, ALL_PRODUCTS))


# === Timing Delays (in seconds) ===
# Tuples represent (min, max) for random.uniform()

DELAYS = {
    "page_load": (3, 6),           # Wait for page to fully load
    "after_search": (2, 4),        # Wait after search submit
    "before_click": (0.3, 1.0),    # Pause before clicking element
    "after_click": (1, 2),         # Pause after clicking
    "scroll_pause": (0.5, 1.5),    # Pause during scrolling
    "between_actions": (1, 3),     # Between major actions
    "typing_pause": (0.1, 0.3),    # Short pause before typing
}


def delay(delay_type: str):
    """Execute a random delay of the specified type."""
    import time
    if delay_type in DELAYS:
        min_delay, max_delay = DELAYS[delay_type]
        time.sleep(random.uniform(min_delay, max_delay))


# === Retry Configuration ===
MAX_SELECTOR_RETRIES = 2         # Times to retry finding element via selector
MAX_AGENTQL_RETRIES = 1          # Times to retry AgentQL (expensive, limit retries)
MAX_PAGE_LOAD_RETRIES = 3        # Times to retry page navigation
ELEMENT_WAIT_TIMEOUT = 10000     # Milliseconds to wait for element

# === Product Selection ===
# Skip first N results (usually sponsored)
SKIP_SPONSORED_COUNT = 2
# Max products to consider when selecting randomly
MAX_PRODUCTS_TO_CONSIDER = 10
