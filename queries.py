"""
AgentQL Semantic Queries for Amazon Automation

These queries are used as FALLBACK when CSS selectors fail.
Queries are designed to be:
- Minimal (batched to reduce API calls)
- Semantic (natural language element descriptions)

Usage: Import queries and use with page.query_elements(QUERY)
"""

# === Search Page Query ===
# Finds all elements needed on the search/home page in one query
SEARCH_PAGE_QUERY = """
{
    search_input
    search_button
}
"""

# === Search Results Query ===
# Batched query for search results page
RESULTS_PAGE_QUERY = """
{
    result_items[] {
        product_title
        product_link
        product_price
        prime_badge
    }
}
"""

# === Product Detail Page Query ===
# All elements needed on product page
PRODUCT_PAGE_QUERY = """
{
    product_title
    buy_now_button
    add_to_cart_button
    product_price
    availability_status
}
"""

# === Detection Queries ===
# Used to detect current page state

DETECT_PAGE_STATE_QUERY = """
{
    search_input
    result_items
    product_title
    buy_now_button
    checkout_form
}
"""

# === Error Detection ===
ERROR_DETECTION_QUERY = """
{
    error_message
    captcha_challenge
    sign_in_form
    out_of_stock_notice
}
"""

# === Specific Element Queries (for targeted fallback) ===
# These are smaller queries for when we just need one element

SEARCH_INPUT_QUERY = """
{
    search_input
}
"""

SEARCH_BUTTON_QUERY = """
{
    search_button
}
"""

BUY_NOW_QUERY = """
{
    buy_now_button
}
"""

ADD_TO_CART_QUERY = """
{
    add_to_cart_button
}
"""
