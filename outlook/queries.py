"""
AgentQL Queries for Outlook Signup

Used as fallback when CSS selectors fail.
Follows AgentQL best practices.
"""

# Step 1: Email Input
EMAIL_STEP_QUERY = """
{
    email_input
    next_button
    error_message
    new_email_link(link to get a new outlook email address)
}
"""

# Step 2: Password Input
PASSWORD_STEP_QUERY = """
{
    password_input
    next_button
}
"""

# Step 3: Name Input
NAME_STEP_QUERY = """
{
    first_name_input
    last_name_input
    next_button
}
"""

# Step 4: Date of Birth
DOB_STEP_QUERY = """
{
    birth_date_fields {
        month_select
        day_select
        year_input
    }
    next_button
}
"""

# Step 5: CAPTCHA
CAPTCHA_STEP_QUERY = """
{
    captcha_frame
    press_and_hold_button(the button you need to press and hold)
}
"""

# Step 6: Privacy Notice
PRIVACY_STEP_QUERY = """
{
    ok_button(button to accept or proceed, labeled OK)
    accept_button
}
"""

# Step 7: Passkey / Interruption
PASSKEY_STEP_QUERY = """
{
    skip_button(button to skip passkey setup, labeled Skip for now or Skip)
    cancel_button(button to cancel passkey creation)
}
"""

# Step 8: Stay Signed In
STAY_SIGNED_IN_QUERY = """
{
    yes_button(button to confirm staying signed in)
    no_button(button to decline staying signed in)
}
"""

# Combined detection query (single query to detect current step)
DETECT_STEP_QUERY = """
{
    email_input
    password_input
    first_name_input
    birth_date_fields {
        year_input
    }
    captcha_frame
    press_and_hold_button
    inbox_link
    welcome_message
}
"""
