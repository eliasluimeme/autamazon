"""
Configuration for Outlook Login Flow.
"""

OUTLOOK_LOGIN_URL = "https://login.live.com/login.srf"

MAX_DURATION = 300  # 5 minutes max for full login flow

# Randomized delays (min, max) in seconds to mimic human behavior
DELAYS = {
    "page_load": (2.0, 4.0),
    "after_input": (0.5, 1.5),
    "after_click": (1.0, 2.5),
    "step_transition": (2.5, 4.5),
}
