"""
Outlook Signup Utilities

Shared utility functions for the outlook signup module.
"""

from amazon.outlook.utils.xpath_cache import (
    extract_xpath,
    extract_and_cache_xpath,
    get_cached_xpath,
    get_cached_css,
    find_element,
    find_element_in_frames,
    try_cached_xpath_in_frames,
    extract_xpath_from_agentql,
    cache_css_selector,
    clear_cache,
    DOMPATH_AVAILABLE,
)

__all__ = [
    "extract_xpath",
    "extract_and_cache_xpath",
    "get_cached_xpath",
    "get_cached_css",
    "find_element",
    "find_element_in_frames",
    "try_cached_xpath_in_frames",
    "extract_xpath_from_agentql",
    "cache_css_selector",
    "clear_cache",
    "DOMPATH_AVAILABLE",
]
