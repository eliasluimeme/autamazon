"""
Outlook Signup Action Handlers

Modular handlers for each step of the Microsoft signup flow.
"""

from amazon.outlook.actions.email import handle_email_step
from amazon.outlook.actions.password import handle_password_step
from amazon.outlook.actions.name import handle_name_step
from amazon.outlook.actions.dob import handle_dob_step
from amazon.outlook.actions.captcha import handle_captcha_step
from amazon.outlook.actions.privacy import handle_privacy_step
from amazon.outlook.actions.passkey import handle_passkey_step
from amazon.outlook.actions.stay_signed_in import handle_stay_signed_in_step
from amazon.outlook.actions.detect import detect_current_step

__all__ = [
    "handle_email_step",
    "handle_password_step",
    "handle_name_step",
    "handle_dob_step",
    "handle_captcha_step",
    "handle_privacy_step",
    "handle_passkey_step",
    "handle_stay_signed_in_step",
    "detect_current_step",
]

