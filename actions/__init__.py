"""
Amazon Automation Actions Module

Contains modular action handlers for:
- Navigation
- Product search
- Product selection
- Account creation / Signup
- Email verification
- Signin email entry
"""

from amazon.actions.navigate import navigate_to_amazon, wait_for_page_load
from amazon.actions.search import search_product, wait_for_search_results
from amazon.actions.product import (
    select_random_product,
    click_buy_now,
    get_search_results,
    is_product_unavailable
)
from amazon.actions.signup import (
    click_create_account,
    fill_registration_form,
    click_continue_registration,
    detect_signup_state,
)
from amazon.actions.detect_state import detect_signup_state
from amazon.actions.cart import handle_cart_interstitial
from amazon.actions.email_verification import handle_email_verification
from amazon.actions.signin_email import is_email_signin_page, handle_email_signin_step

__all__ = [
    "navigate_to_amazon",
    "wait_for_page_load",
    "search_product",
    "wait_for_search_results",
    "select_random_product",
    "click_buy_now",
    "get_search_results",
    "is_product_unavailable",
    "click_create_account",
    "fill_registration_form",
    "click_continue_registration",
    "detect_signup_state",
    "handle_cart_interstitial",
    "handle_email_verification",
    "is_email_signin_page",
    "handle_email_signin_step",
]
