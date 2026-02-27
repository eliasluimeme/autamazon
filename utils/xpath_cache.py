import os
import json
import time
from loguru import logger
try:
    from filelock import FileLock
except ImportError:
    class FileLock:
        def __init__(self, lock_file, timeout=10): pass
        def __enter__(self): return self
        def __exit__(self, exc_type, exc_val, exc_tb): pass
    logger.warning("filelock module not found. Run 'pip install filelock' for parallel safety.")

# Try to import playwright-dompath for XPath extraction
try:
    from playwright_dompath.dompath_sync import xpath_path
    DOMPATH_AVAILABLE = True
except ImportError:
    logger.warning("playwright_dompath not available - install with: pip install playwright-dompath")
    DOMPATH_AVAILABLE = False
    xpath_path = None

# Cache file in the actions directory to match user's preferred pattern
CACHE_FILE = os.path.abspath(os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", ".selector_cache.json"))
LOCK_FILE = f"{CACHE_FILE}.lock"

def _load_cache() -> dict:
    """Load the selector cache from disk."""
    try:
        os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
        with FileLock(LOCK_FILE, timeout=5):
            if os.path.exists(CACHE_FILE):
                with open(CACHE_FILE, 'r') as f:
                    return json.load(f)
    except Exception as e:
        logger.debug(f"Failed to load selector cache: {e}")
    return {}

def _save_cache(cache: dict):
    """Save the selector cache to disk."""
    try:
        os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
        with FileLock(LOCK_FILE, timeout=5):
            with open(CACHE_FILE, 'w') as f:
                json.dump(cache, f, indent=2)
    except Exception as e:
        logger.debug(f"Failed to save selector cache: {e}")


def get_cached_xpath(key: str) -> str:
    """Get a cached XPath by key."""
    cache = _load_cache()
    if key in cache:
        return cache[key].get('xpath')
    return None

def extract_and_cache_xpath(element, key: str):
    """Extract XPath from element and cache it."""
    if not DOMPATH_AVAILABLE or element is None:
        return None
    
    try:
        xpath = xpath_path(element)
        if xpath:
            cache = _load_cache()
            cache[key] = {
                'xpath': xpath,
                'timestamp': time.time()
            }
            _save_cache(cache)
            logger.info(f"✅ Cached XPath for '{key}': {xpath[:50]}...")
            return xpath
    except Exception as e:
        logger.debug(f"Failed to extract/cache XPath for {key}: {e}")
    return None
