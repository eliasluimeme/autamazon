from utils.mouse_random_click import human_like_mouse_click, reset_mouse_state
from utils.human_type import human_like_type
from utils.mobile_touch import human_like_mobile_tap, human_like_mobile_scroll, human_like_mobile_type
from loguru import logger

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
            return human_like_mobile_tap(self.page, locator)
        else:
            # Use sophisticated mouse click for desktop
            return human_like_mouse_click(locator, speed_mode="medium")

    def smart_type(self, locator, text):
        """
        Automatically chooses Keyboard vs Soft-Keyboard based on device type.
        """
        if self.device_type == "mobile":
            return human_like_mobile_type(locator, text)
        else:
            # Use sophisticated typing for desktop
            return human_like_type(locator, text, speed_mode="medium")

    def smart_scroll(self):
        """
        Mouse Wheel vs Finger Swipe.
        
        Note: This is a generic scroll action. For element-specific scrolling, 
        the desktop implementation already handles it within human_like_mouse_click.
        """
        if self.device_type == "mobile":
            human_like_mobile_scroll(self.page, direction="down")
        else:
            # Simple random scroll for desktop generic behavior
            import random
            import time
            
            try:
                # Scroll down a random amount
                scroll_amount = random.randint(300, 700)
                self.page.mouse.wheel(0, scroll_amount)
                time.sleep(random.uniform(0.5, 1.5))
            except Exception as e:
                logger.warning(f"Smart scroll (desktop) failed: {e}")
