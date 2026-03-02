from loguru import logger
import random
import time

# Try to import sophisticated utilities, fall back to None if missing
try:
    from utils.mouse_random_click import human_like_mouse_click, reset_mouse_state
except ImportError:
    logger.warning("Desktop mouse utilities not available in HumanInput")
    human_like_mouse_click = None
    reset_mouse_state = lambda: None

try:
    from utils.human_type import human_like_type
except ImportError:
    logger.warning("Human typing utilities not available in HumanInput")
    human_like_type = None

try:
    from utils.mobile_touch import human_like_mobile_tap, human_like_mobile_scroll, human_like_mobile_type
except ImportError:
    logger.warning("Mobile touch utilities not available in HumanInput")
    human_like_mobile_tap = None
    human_like_mobile_scroll = None
    human_like_mobile_type = None

class HumanInput:
    def __init__(self, page, device_type="desktop"):
        """
        Initialize the HumanInput controller.
        
        Args:
            page: The Playwright page object.
            device_type: 'desktop' or 'mobile'.
        """
        self.page = page
        self.device_type = device_type.lower()
        
        # Reset mouse state on initialization to prevent artifacts from previous sessions
        if self.device_type != "mobile":
            reset_mouse_state()

    def smart_click(self, locator):
        """
        Automatically chooses Click vs Tap based on the device type.
        """
        if self.device_type == "mobile":
            if human_like_mobile_tap:
                return human_like_mobile_tap(self.page, locator)
            else:
                return locator.click()
        else:
            # Use sophisticated mouse click for desktop
            if human_like_mouse_click:
                return human_like_mouse_click(locator, speed_mode="medium")
            else:
                return locator.click()

    def smart_type(self, locator, text):
        """
        Automatically chooses Keyboard vs Soft-Keyboard based on device type.
        """
        if self.device_type == "mobile":
            if human_like_mobile_type:
                return human_like_mobile_type(locator, text)
            else:
                return locator.fill(text)
        else:
            # Use sophisticated typing for desktop
            if human_like_type:
                return human_like_type(locator, text, speed_mode="medium")
            else:
                return locator.fill(text)

    def smart_scroll(self):
        """
        Mouse Wheel vs Finger Swipe.
        """
        if self.device_type == "mobile":
            if human_like_mobile_scroll:
                human_like_mobile_scroll(self.page, direction="down")
            else:
                self.page.mouse.wheel(0, 500)
        else:
            try:
                # Scroll down a random amount
                scroll_amount = random.randint(300, 700)
                self.page.mouse.wheel(0, scroll_amount)
                time.sleep(random.uniform(0.5, 1.5))
            except Exception as e:
                logger.warning(f"Smart scroll (desktop) failed: {e}")
