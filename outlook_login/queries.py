"""
AgentQL Queries for Outlook Login
"""

DETECT_STEP_QUERY = """
{
    email_input
    password_input
    skip_for_now_button
    stay_signed_in_yes_button
    stay_signed_in_checkbox
    passkey_skip_button
    cancel_button
    try_again_button
    privacy_ok_button
    error_message
}
"""

EMAIL_STEP_QUERY = """
{
    email_input
    next_button
}
"""

PASSWORD_STEP_QUERY = """
{
    password_input
    signin_button
}
"""

SKIP_STEP_QUERY = """
{
    skip_for_now_button
}
"""

STAY_SIGNED_IN_STEP_QUERY = """
{
    stay_signed_in_checkbox
    stay_signed_in_yes_button
}
"""
