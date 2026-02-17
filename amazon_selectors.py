"""
Amazon CSS Selectors

Primary method for locating elements. Organized by page context and device type.
AgentQL queries in queries.py are used as fallback when these fail.

Selector priority:
1. Device-specific selector (mobile/desktop)
2. Universal selector
3. Fallback to AgentQL

Maintenance: When selectors break, check Amazon's current markup and update here.
"""

# === Search Page Selectors ===
SEARCH_SELECTORS = {
    "search_input": {
        "mobile": "#nav-search-keywords",
        "desktop": "#twotabsearchtextbox",
        "universal": "#twotabsearchtextbox, #nav-search-keywords, input[name='field-keywords']",
    },
    "search_button": {
        "universal": "#nav-search-submit-button, .nav-search-submit input[type='submit']",
    },
    "search_form": {
        "universal": "#nav-search-bar-form, form[name='site-search']",
    },
}

# === Search Results Page Selectors ===
RESULTS_SELECTORS = {
    "result_items": {
        # Main product cards in search results
        "universal": "div[data-component-type='s-search-result']",
    },
    "product_link": {
        # Link to product detail page (within result item)
        "universal": "a.a-link-normal.s-underline-text, h2 a.a-link-normal",
    },
    "product_title": {
        # Product title text (within result item)
        "universal": "span.a-size-base-plus.a-color-base, h2 span.a-text-normal",
    },
    "product_price": {
        "universal": "span.a-price-whole",
    },
    "prime_badge": {
        "universal": "i.a-icon-prime, span.a-icon-prime",
    },
    "sponsored_label": {
        # Used to detect and skip sponsored products
        "universal": "span.s-label-popover-default, span:has-text('Sponsored')",
    },
    "next_page": {
        "universal": "a.s-pagination-next, .s-pagination-next",
    },
}

# === Product Detail Page Selectors ===
PRODUCT_SELECTORS = {
    "product_title": {
        "universal": "#productTitle, #title",
    },
    "buy_now_button": {
        # Direct purchase button
        "universal": "#buy-now-button, input#buy-now-button, #buyNow",
        "mobile": "#buyNow-announce, #buy-now-button",
    },
    "add_to_cart_button": {
        "universal": "#add-to-cart-button, input#add-to-cart-button",
    },
    "quantity_dropdown": {
        "universal": "#quantity, select#quantity",
    },
    "price": {
        "universal": "#priceblock_ourprice, #priceblock_dealprice, span.a-price-whole",
    },
    "availability": {
        "universal": "#availability span, #outOfStock",
    },
    "product_image": {
        "universal": "#imgTagWrapperId img, #landingImage",
    },
}

# === Mobile-Specific Navigation ===
MOBILE_NAV_SELECTORS = {
    "hamburger_menu": "#nav-hamburger-menu",
    "search_icon": "#nav-search-bar-form a.nav-search-submit",
    "back_button": "a.nav-bb-back, .a-back-button",
    "mobile_search_bar": "#nav-search-keywords",
}

# === Checkout Flow Selectors (for future expansion) ===
CHECKOUT_SELECTORS = {
    "sign_in_button": {
        "universal": "#signInSubmit, input[name='signIn']",
    },
    "continue_button": {
        "universal": "input[name='continue'], .a-button-primary input",
    },
    "place_order_button": {
        "universal": "#submitOrderButtonId, #placeYourOrder input",
    },
}


def get_selector(page_context: str, element_key: str, device_type: str = "universal") -> str:
    """
    Get selector for an element.
    
    Args:
        page_context: 'search', 'results', 'product', 'checkout', 'mobile_nav'
        element_key: The element identifier
        device_type: 'mobile', 'desktop', or 'universal'
    
    Returns:
        CSS selector string, or None if not found
    """
    selector_maps = {
        "search": SEARCH_SELECTORS,
        "results": RESULTS_SELECTORS,
        "product": PRODUCT_SELECTORS,
        "checkout": CHECKOUT_SELECTORS,
        "mobile_nav": {"selectors": MOBILE_NAV_SELECTORS},
    }
    
    context_selectors = selector_maps.get(page_context, {})
    
    # Handle mobile_nav which is a flat dict
    if page_context == "mobile_nav":
        return MOBILE_NAV_SELECTORS.get(element_key)
    
    element_selectors = context_selectors.get(element_key, {})
    
    # Try device-specific first, then universal
    if device_type in element_selectors:
        return element_selectors[device_type]
    
    return element_selectors.get("universal")


def get_all_selectors_for_element(page_context: str, element_key: str) -> list:
    """
    Get all possible selectors for an element (for fallback attempts).
    
    Returns list of selectors to try in order.
    """
    selector_maps = {
        "search": SEARCH_SELECTORS,
        "results": RESULTS_SELECTORS,
        "product": PRODUCT_SELECTORS,
        "checkout": CHECKOUT_SELECTORS,
    }
    
    context_selectors = selector_maps.get(page_context, {})
    element_selectors = context_selectors.get(element_key, {})
    
    selectors = []
    # Add in priority order: mobile, desktop, universal
    for key in ["mobile", "desktop", "universal"]:
        if key in element_selectors:
            selectors.append(element_selectors[key])
    
    return selectors
