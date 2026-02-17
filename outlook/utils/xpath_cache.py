"""
XPath Extraction and Caching Utility (Centralized)

Provides functions to extract XPath from Playwright/AgentQL elements
and cache them for self-healing automation.

Cache location:  data/xpath_cache/outlook_selectors.json
In-memory cache avoids repeated disk reads for maximum speed.

Usage:
    from amazon.outlook.utils.xpath_cache import find_element, get_cached_xpath

    # Fast element lookup: cached xpath → css fallback → None
    element = find_element(page, "email_input", timeout=3000)

    # When finding an element via AgentQL, cache its XPath
    element = response.some_button
    extract_and_cache_xpath(element, "captcha_button")
"""

import os
import json
import time
from loguru import logger

# Import playwright_dompath for XPath extraction
try:
    from playwright_dompath.dompath_sync import xpath_path
    DOMPATH_AVAILABLE = True
except ImportError:
    logger.warning("playwright_dompath not available - install with: pip install playwright-dompath")
    DOMPATH_AVAILABLE = False
    xpath_path = None


# ---------------------------------------------------------------------------
# Cache file location — centralised under data/xpath_cache/
# ---------------------------------------------------------------------------
_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
CACHE_FILE = os.path.join(_PROJECT_ROOT, "data", "xpath_cache", "outlook_selectors.json")

# In-memory cache for zero-cost repeated lookups
_memory_cache: dict | None = None
_memory_cache_mtime: float = 0.0


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _load_cache() -> dict:
    """Load the XPath cache from disk, with in-memory caching."""
    global _memory_cache, _memory_cache_mtime

    try:
        if not os.path.exists(CACHE_FILE):
            return {}

        file_mtime = os.path.getmtime(CACHE_FILE)

        # Return in-memory version if file hasn't changed
        if _memory_cache is not None and file_mtime == _memory_cache_mtime:
            return _memory_cache

        with open(CACHE_FILE, "r") as f:
            data = json.load(f)

        _memory_cache = data
        _memory_cache_mtime = file_mtime
        return data

    except Exception as e:
        logger.debug(f"Failed to load xpath cache: {e}")
        return {}


def _save_cache(cache: dict):
    """Save the XPath cache to disk and refresh in-memory copy."""
    global _memory_cache, _memory_cache_mtime

    try:
        os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
        with open(CACHE_FILE, "w") as f:
            json.dump(cache, f, indent=2)
        _memory_cache = cache
        _memory_cache_mtime = os.path.getmtime(CACHE_FILE)
    except Exception as e:
        logger.debug(f"Failed to save xpath cache: {e}")


def _invalidate_memory():
    """Force next _load_cache() to read from disk."""
    global _memory_cache, _memory_cache_mtime
    _memory_cache = None
    _memory_cache_mtime = 0.0


# ---------------------------------------------------------------------------
# XPath validation
# ---------------------------------------------------------------------------

def _is_valid_xpath(xpath: str) -> bool:
    """
    Validate that an XPath is specific enough to be cached.
    Rejects overly generic selectors that would match on multiple pages.
    """
    if not xpath:
        return False

    invalid_patterns = [
        '//*[@id="root"]',
        '//*[@id="app"]',
        '//*[@id="main"]',
        '//body',
        '//html',
        '//*[@id="container"]',
        '//*[@id="wrapper"]',
        '//*[@id="content"]',
        '//*[@id="page"]',
        '//*[@id="view"]',
    ]

    xpath_lower = xpath.lower().strip()
    for pattern in invalid_patterns:
        if xpath_lower == pattern.lower():
            logger.warning(f"⚠️ Rejecting generic XPath: {xpath}")
            return False

    if len(xpath) < 15:
        logger.warning(f"⚠️ Rejecting short XPath: {xpath}")
        return False

    return True


# ---------------------------------------------------------------------------
# Public API — extraction & caching
# ---------------------------------------------------------------------------

def extract_xpath(element) -> str:
    """
    Extract XPath from a Playwright locator or AgentQL element.

    Returns:
        XPath string or None if extraction fails
    """
    if not DOMPATH_AVAILABLE:
        logger.debug("playwright_dompath not available")
        return None

    try:
        xp = xpath_path(element)
        logger.debug(f"Extracted XPath: {xp[:60]}...")
        return xp
    except Exception as e:
        logger.debug(f"XPath extraction failed: {e}")
        return None


def extract_and_cache_xpath(element, key: str, metadata: dict = None) -> str:
    """
    Extract XPath from element and cache it for future use.

    Args:
        element: Playwright locator or AgentQL element
        key: Cache key (e.g., "captcha_button", "dob_day")
        metadata: Optional metadata to store with the xpath

    Returns:
        XPath string or None if extraction fails
    """
    xp = extract_xpath(element)

    if xp and _is_valid_xpath(xp):
        cache = _load_cache()

        # Preserve existing CSS selector if present
        existing_css = None
        if key in cache and isinstance(cache[key], dict):
            existing_css = cache[key].get("css")

        cache[key] = {
            "xpath": xp,
            "css": existing_css,
            "timestamp": time.time(),
            "metadata": metadata or {},
        }
        _save_cache(cache)
        logger.info(f"✅ Cached XPath for '{key}': {xp[:50]}")

    return xp


def cache_css_selector(key: str, css: str, metadata: dict = None):
    """
    Store a working CSS selector back into the cache for a given key.
    """
    cache = _load_cache()

    if key in cache and isinstance(cache[key], dict):
        cache[key]["css"] = css
        cache[key]["timestamp"] = time.time()
        if metadata:
            cache[key]["metadata"] = metadata
    else:
        cache[key] = {
            "xpath": None,
            "css": css,
            "timestamp": time.time(),
            "metadata": metadata or {},
        }

    _save_cache(cache)
    logger.debug(f"Cached CSS for '{key}': {css[:50]}")


# ---------------------------------------------------------------------------
# Public API — retrieval
# ---------------------------------------------------------------------------

def get_cached_xpath(key: str) -> str:
    """
    Get a cached XPath by key.

    Returns:
        XPath string or None if not cached
    """
    cache = _load_cache()
    entry = cache.get(key)
    if entry:
        xp = entry.get("xpath") if isinstance(entry, dict) else entry
        if xp:
            logger.debug(f"📦 Using cached XPath for '{key}'")
            return xp
    return None


def get_cached_css(key: str) -> str:
    """
    Get a cached CSS selector by key.

    Returns:
        CSS selector string or None
    """
    cache = _load_cache()
    entry = cache.get(key)
    if entry and isinstance(entry, dict):
        css = entry.get("css")
        if css:
            logger.debug(f"📦 Using cached CSS for '{key}'")
            return css
    return None


def get_cached_xpath_with_metadata(key: str) -> tuple:
    """
    Get cached XPath and its metadata.

    Returns:
        (xpath, metadata) tuple or (None, None) if not cached
    """
    cache = _load_cache()
    entry = cache.get(key)
    if entry and isinstance(entry, dict):
        return entry.get("xpath"), entry.get("metadata", {})
    return None, None


# ---------------------------------------------------------------------------
# Public API — smart element finder
# ---------------------------------------------------------------------------

def find_element(page, key: str, timeout: int = 3000, css_fallback: str = None):
    """
    Find an element using the optimal strategy:
      1. Cached XPath  (fastest — no DOM traversal overhead)
      2. Cached CSS    (fast — browser-native querySelector)
      3. css_fallback  (explicit fallback CSS provided by caller)

    This does NOT call AgentQL — the caller should handle that tier.

    Args:
        page: Playwright page
        key: Cache key (e.g. "email_input", "passkey_skip_button")
        timeout: Visibility timeout in ms
        css_fallback: Optional explicit CSS selector to try last

    Returns:
        Playwright locator or None
    """
    # --- Tier 1: Cached XPath ---
    cached_xp = get_cached_xpath(key)
    if cached_xp:
        try:
            loc = page.locator(f"xpath={cached_xp}").first
            if loc.is_visible(timeout=min(timeout, 2000)):
                logger.debug(f"✓ Found '{key}' via cached XPath")
                return loc
        except Exception:
            pass

    # --- Tier 2: Cached CSS ---
    cached_css = get_cached_css(key)
    if cached_css:
        # CSS may be a comma-separated multi-selector, try each individually
        for selector in cached_css.split(", "):
            selector = selector.strip()
            if not selector:
                continue
            try:
                loc = page.locator(selector).first
                if loc.is_visible(timeout=min(timeout, 1500)):
                    logger.debug(f"✓ Found '{key}' via cached CSS: {selector[:40]}")
                    return loc
            except Exception:
                continue

    # --- Tier 3: Explicit CSS fallback ---
    if css_fallback:
        for selector in css_fallback.split(", "):
            selector = selector.strip()
            if not selector:
                continue
            try:
                loc = page.locator(selector).first
                if loc.is_visible(timeout=min(timeout, 1500)):
                    logger.debug(f"✓ Found '{key}' via fallback CSS: {selector[:40]}")
                    return loc
            except Exception:
                continue

    return None


def find_element_in_frames(page, key: str, timeout: int = 1000):
    """
    Try to find an element using cached XPath across all frames.
    Useful for elements inside iframes (e.g. CAPTCHA).

    Returns:
        (frame, locator) tuple if found, (None, None) otherwise
    """
    cached_xp = get_cached_xpath(key)
    if not cached_xp:
        return None, None

    logger.debug(f"Trying cached XPath '{key}' in all frames...")

    for frame in page.frames:
        try:
            locator = frame.locator(f"xpath={cached_xp}").first
            if locator.is_visible(timeout=timeout):
                box = locator.bounding_box()
                if box and box.get("width", 0) > 0:
                    logger.info(f"✅ Found element via cached XPath '{key}'")
                    return frame, locator
        except Exception:
            continue

    logger.debug(f"Cached XPath '{key}' not found in any frame")
    return None, None


# Backward-compatible alias
try_cached_xpath_in_frames = find_element_in_frames


# ---------------------------------------------------------------------------
# Public API — cache management
# ---------------------------------------------------------------------------

def clear_cache(key: str = None):
    """
    Clear cached XPath(s).

    Args:
        key: Specific key to clear, or None to clear all
    """
    if key:
        cache = _load_cache()
        if key in cache:
            del cache[key]
            _save_cache(cache)
            logger.debug(f"Cleared cache for '{key}'")
    else:
        _save_cache({})
        logger.debug("Cleared all xpath cache")


def extract_xpath_from_agentql(agentql_element, key: str, page=None) -> str:
    """
    Extract XPath from an AgentQL element and cache it.
    Also tries to validate the XPath works.

    Args:
        agentql_element: Element returned by AgentQL query
        key: Cache key
        page: Optional page to validate xpath on

    Returns:
        XPath string or None
    """
    xp = extract_and_cache_xpath(agentql_element, key)

    # Optionally validate the xpath
    if xp and page:
        try:
            for frame in page.frames:
                try:
                    loc = frame.locator(f"xpath={xp}").first
                    if loc.is_visible(timeout=500):
                        logger.debug(f"Validated XPath for '{key}'")
                        return xp
                except Exception:
                    continue
            logger.debug(f"XPath for '{key}' extracted but not validated")
        except Exception:
            pass

    return xp
