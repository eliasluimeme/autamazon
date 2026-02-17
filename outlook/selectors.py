"""
CSS Selectors for Microsoft Outlook Signup

Organized by signup step for selector-first approach.
AgentQL queries in queries.py are used as fallback.
"""

SELECTORS = {
    # Email step
    "email": {
        "input": "#MemberName, input[name='MemberName'], input[type='email']",
        "next_button": "#iSignupAction, button[type='submit']",
        "new_email_link": "#liveSwitch, a:has-text('Get a new email address')",
        "error_message": "#MemberNameError, .error, .alert-error, div:has-text('already taken')",
        # Suggestion buttons - try multiple patterns
        "suggestions": "button[id^='sugg_'], button[name^='sugg_'], .suggestion-button, button[id*='Sugg'], #suggestions button, div#suggestions button",
    },
    
    # Password step
    "password": {
        "input": "#PasswordInput, input[name='Password'], input[type='password']",
        "next_button": "#iSignupAction, button[type='submit']",
    },
    
    # Name step
    "name": {
        "first_name": "#FirstName, input[name='FirstName']",
        "last_name": "#LastName, input[name='LastName']",
        "next_button": "#iSignupAction, button[type='submit']",
    },
    
    # Date of birth step
    # Microsoft uses custom dropdown buttons, not native <select> elements
    "dob": {
        "month_select": "#BirthMonth, select[name='BirthMonth'], select[aria-label='Month'], [aria-label='Month'], button[aria-label*='Month'], div[aria-haspopup][id*='Month'], [data-testid='BirthMonth'], [id*='BirthMonth']",
        "day_select": "#BirthDay, select[name='BirthDay'], select[aria-label='Day'], [aria-label='Day'], button[aria-label*='Day'], div[aria-haspopup][id*='Day'], [data-testid='BirthDay'], [id*='BirthDay']",
        "year_input": "#BirthYear, input[name='BirthYear'], input[placeholder='Year'], input[id*='Year'], input[aria-label*='year'], input[aria-label*='Year'], [data-testid='BirthYear']",
        "country_select": "#Country, select[name='Country'], select[id*='Country'], [aria-label='Country'], button[aria-label*='Country']",
        "next_button": "#iSignupAction, button[type='submit'], #idSIButton9, button[id*='Signup'], button[id*='Next'], button:has-text('Next')",
    },
    
    # Captcha step
    "captcha": {
        "frame": "iframe[src*='captcha'], iframe[title*='challenge'], iframe[src*='enforcement']",
        "press_hold_button": "button:has-text('Press and hold'), #holdButton, button[id*='hold'], button:has-text('Hold to confirm')",
    },
    
    # Privacy notice step
    "privacy": {
        "ok_button": "button:has-text('OK'), #acceptButton, #idBtn_Accept, button[type='submit']",
    },
    
    # Passkey / Interruption step
    "passkey": {
        # Various buttons that indicate the passkey screen
        "skip_button": "button:has-text('Skip for now'), button:has-text('Skip'), a:has-text('Skip for now')",
        "cancel_button": "button:has-text('Cancel'), #idBtn_Back",
        # Indicators for detection
        "header": "h1:has-text('passkey'), h2:has-text('passkey'), h1:has-text('Passkey'), h2:has-text('Passkey'), div:has-text('passkey')",
        # Alternative indicators - the "Go passwordless" or similar prompts
        "go_passwordless": "button:has-text('Go passwordless'), a:has-text('Go passwordless'), :text('passwordless')",
    },
    
    # Stay Signed In step
    "stay_signed_in": {
        "yes_button": "button:has-text('Yes'), #idSIButton9, #acceptButton",
        "no_button": "button:has-text('No'), #idBtn_Back",
    },
    
    # Success indicators
    "success": {
        "inbox": "a[href*='outlook.live.com'], a:has-text('Inbox')",
        "welcome": "text=Welcome, text=Get started",
    },
}

# Mobile-specific selectors (if different)
MOBILE_SELECTORS = {
    # Most selectors work across devices
    # Add mobile-specific overrides here if needed
}

def get_selector(step: str, element: str, is_mobile: bool = False) -> str:
    """
    Get the appropriate selector for a step/element combo.
    
    Args:
        step: Step name (email, password, name, dob, captcha, success)
        element: Element name within the step
        is_mobile: Whether to use mobile-specific selectors
        
    Returns:
        CSS selector string
    """
    if is_mobile and step in MOBILE_SELECTORS and element in MOBILE_SELECTORS[step]:
        return MOBILE_SELECTORS[step][element]
    
    return SELECTORS.get(step, {}).get(element, "")
