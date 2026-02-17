"""
Outlook Signup Module for Amazon Automation

This module handles Microsoft Outlook account creation as part of the
Amazon automation workflow. The created email is used for Amazon account verification.

Follows amazon architecture:
- Selector-first, AgentQL fallback
- Uses DeviceAdapter for human-like interactions
- Modular action handlers
"""

from amazon.outlook.actions import (
    handle_email_step,
    handle_password_step,
    handle_name_step,
    handle_dob_step,
    handle_captcha_step,
)
from amazon.outlook.run import run_outlook_signup

__all__ = [
    "run_outlook_signup",
    "handle_email_step",
    "handle_password_step",
    "handle_name_step",
    "handle_dob_step",
    "handle_captcha_step",
]
