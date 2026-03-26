"""
CSS Selectors for Microsoft Outlook Login

Organized by login step for selector-first approach.
"""

SELECTORS = {
    "email": {
        "input": "#i0116, input[name='loginfmt'], input[type='email']",
        "next_button": "#idSIButton9, button[type='submit']",
        "error_message": "#usernameError, .alert-error"
    },
    
    "password": {
        "input": "#i0118, input[name='passwd'], input[type='password']",
        "signin_button": "#idSIButton9, button[type='submit']",
        "error_message": "#passwordError, .alert-error"
    },
    
    "skip": {
        "skip_button": "#iShowSkip, a:has-text('Skip for now'), a:has-text('Skip'), button:has-text('Skip for now')"
    },
    
    "stay_signed_in": {
        "checkbox_label": "//*[@id='pageContent']/div/form/div[3]/div[1]/div/label", # Original xpath provided
        "checkbox": "input[name='DontShowAgain'], input[type='checkbox']",
        "yes_button": "#acceptButton, button:has-text('Yes')",
        "no_button": "#declineButton, #idBtn_Back, button:has-text('No')"
    },

    "passkey": {
        "skip_button": "button:has-text('Skip for now'), a:has-text('Skip for now')",
        "cancel_button": "button:has-text('Cancel'), a:has-text('Cancel')",
        "header": "h1:has-text('passkey'), h2:has-text('passkey'), h1:has-text('Passkey'), h2:has-text('Passkey')",
    },

    "privacy": {
        "ok_button": "button:has-text('OK'), #acceptButton, #idBtn_Accept, button[type='submit']",
    },
    
    "success": {
        "inbox": "a[href*='outlook.live.com'], a:has-text('Inbox')",
    }
}
