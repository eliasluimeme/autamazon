"""
Configuration for Outlook Signup Automation
"""

# Microsoft signup URLs
OUTLOOK_SIGNUP_URL = "https://signup.live.com/signup?lic=1"
OUTLOOK_LOGIN_URL = "https://login.live.com/"

# Preflight check URLs  
PROXY_CHECK_URLS = [
    "https://httpbin.org/ip",
    "https://api.ipify.org?format=json",
]

# Timing delays
DELAYS = {
    "page_load": (3, 6),
    "after_input": (0.5, 1.5),
    "after_click": (2, 4),
    "step_transition": (3, 5),
    "captcha_hold": (10, 12),
}

# Maximum automation duration (seconds)
MAX_DURATION = 500  # 8 minutes

# Step detection order
STEP_ORDER = ["EMAIL", "PASSWORD", "NAME", "DOB", "CAPTCHA", "SUCCESS"]
