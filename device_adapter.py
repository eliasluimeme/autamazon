"""
Device Adapter for Amazon Automation

Detects device type (mobile/desktop) and routes actions to appropriate utilities.
Uses mobile_touch.py for mobile devices and mouse_random_click.py for desktop.
"""

import sys
import os
import time
import random
from loguru import logger

# Ensure we can import from amazon/utils
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Try to import human-like utilities from local utils folder
try:
    from amazon.utils.mobile_touch import (
        human_like_mobile_tap,
        human_like_mobile_scroll,
        human_like_mobile_type
    )
    MOBILE_UTILS_AVAILABLE = True
except ImportError:
    try:
        from utils.mobile_touch import (
            human_like_mobile_tap,
            human_like_mobile_scroll,
            human_like_mobile_type
        )
        MOBILE_UTILS_AVAILABLE = True
    except ImportError:
        logger.warning("Mobile touch utilities not available")
        MOBILE_UTILS_AVAILABLE = False
        human_like_mobile_tap = None
        human_like_mobile_scroll = None
        human_like_mobile_type = None

try:
    from amazon.utils.mouse_random_click import human_like_mouse_click
    DESKTOP_UTILS_AVAILABLE = True
except ImportError:
    try:
        from utils.mouse_random_click import human_like_mouse_click
        DESKTOP_UTILS_AVAILABLE = True
    except ImportError:
        logger.warning("Desktop mouse utilities not available")
        DESKTOP_UTILS_AVAILABLE = False
        human_like_mouse_click = None

try:
    from amazon.utils.human_type import human_like_type
    TYPING_UTILS_AVAILABLE = True
except ImportError:
    try:
        from utils.human_type import human_like_type
        TYPING_UTILS_AVAILABLE = True
    except ImportError:
        logger.warning("Human typing utilities not available")
        TYPING_UTILS_AVAILABLE = False
        human_like_type = None


class DeviceAdapter:
    """
    Wraps all user interactions to be device-appropriate.
    
    Automatically detects device type on initialization and routes
    all actions to the correct utility (mobile touch vs desktop mouse).
    """
    
    def __init__(self, page):
        """
        Initialize device adapter with a page.
        
        Args:
            page: Playwright/Patchright page object
        """
        self.page = page
        self.device_type = self.detect_device()
        logger.info(f"DeviceAdapter initialized: {self.device_type.upper()} mode")
    
    def detect_device(self) -> str:
        """
        Detect if browser is in mobile emulation mode.
        
        Uses navigator.maxTouchPoints to detect touch capability.
        
        Returns:
            'mobile' or 'desktop'
        """
        try:
            is_touch = self.page.evaluate("() => navigator.maxTouchPoints > 0")
            if is_touch:
                logger.debug("📱 Detected Mobile Device (Touch enabled)")
                return "mobile"
        except Exception as e:
            logger.warning(f"Device detection failed: {e}")
        
        logger.debug("🖥️ Detected Desktop Device")
        return "desktop"
    
    def is_mobile(self) -> bool:
        """Check if current device is mobile."""
        return self.device_type == "mobile"
    
    def is_desktop(self) -> bool:
        """Check if current device is desktop."""
        return self.device_type == "desktop"
    
    def tap(self, element, description: str = "element") -> bool:
        """
        Human-like tap (mobile) or click (desktop).
        
        Args:
            element: Playwright locator or element
            description: Description for logging
            
        Returns:
            True if successful, False otherwise
        """
        try:
            if self.page.is_closed():
                logger.error("Page closed. Cannot tap.")
                return False

            # Small pause before action (human-like)
            time.sleep(random.uniform(0.2, 0.5))
            
            if self.device_type == "mobile" and MOBILE_UTILS_AVAILABLE:
                logger.info(f"📱 [Mobile] Tapping {description}...")
                result = human_like_mobile_tap(self.page, element)
                if result:
                    return True
            elif self.device_type == "desktop" and DESKTOP_UTILS_AVAILABLE:
                logger.info(f"🖥️ [Desktop] Clicking {description}...")
                result = human_like_mouse_click(element, speed_mode="fast")
                if result is not None:
                    return True
            
            # Fallback to standard click
            logger.info(f"Fallback click on {description}")
            element.click(force=True)
            return True
            
        except Exception as e:
            error_msg = str(e)
            # Handle specific "Can't query n-th element" error (stale handle/race condition)
            if "query n-th element" in error_msg:
                logger.warning(f"Element detached/stale during tap ({description}), retrying...")
                try:
                    time.sleep(0.5)
                    # Retry force click (re-query happens automatically if using Locator)
                    element.click(force=True)
                    return True
                except Exception as retry_e:
                    logger.warning(f"Retry failed: {retry_e}")
                    return False
            
            logger.warning(f"Tap/click failed for {description}: {e}")
            try:
                element.click(force=True)
                return True
            except:
                return False
    


    def type_text(self, element, text: str, description: str = "input") -> bool:
        """
        Human-like typing adapted to device.
        
        Args:
            element: Playwright locator or element
            text: Text to type
            description: Description for logging
            
        Returns:
            True if successful, False otherwise
        """
        try:
            if self.page.is_closed():
                logger.error("Page closed. Cannot type.")
                return False

            # Small pause before typing
            time.sleep(random.uniform(0.1, 0.3))
            
            if self.device_type == "mobile" and MOBILE_UTILS_AVAILABLE:
                logger.info(f"📱 [Mobile] Typing into {description}...")
                result = human_like_mobile_type(element, text)
                if result:
                    return True
            elif TYPING_UTILS_AVAILABLE:
                logger.info(f"🖥️ [Desktop] Typing into {description}...")
                result = human_like_type(element, text, speed_mode="medium")
                if result:
                    return True
            
            # Fallback to standard fill
            logger.info(f"Fallback typing into {description}")
            element.fill("")
            element.fill(text)
            return True
            
        except Exception as e:
            logger.warning(f"Type failed for {description}: {e}")
            try:
                element.fill(text)
                return True
            except:
                return False
    
    def scroll(self, direction: str = "down", magnitude: str = "medium") -> bool:
        """
        Device-appropriate scrolling.
        
        Args:
            direction: 'up' or 'down'
            magnitude: 'small', 'medium', or 'large'
            
        Returns:
            True if successful
        """
        try:
            if self.page.is_closed():
                logger.error("Page closed. Cannot scroll.")
                return False
            
            if self.device_type == "mobile" and MOBILE_UTILS_AVAILABLE:
                logger.debug(f"📱 [Mobile] Scrolling {direction}...")
                human_like_mobile_scroll(self.page, direction=direction, magnitude=magnitude)
            else:
                # Desktop scroll via mouse wheel
                logger.debug(f"🖥️ [Desktop] Scrolling {direction}...")
                scroll_amounts = {"small": 200, "medium": 400, "large": 600}
                amount = scroll_amounts.get(magnitude, 400)
                if direction == "up":
                    amount = -amount
                self.page.mouse.wheel(0, amount)
            
            time.sleep(random.uniform(0.3, 0.6))
            return True
            
        except Exception as e:
            logger.warning(f"Scroll failed: {e}")
            return False
    
    def scroll_to_element(self, element, description: str = "element") -> bool:
        """
        Scroll element into view with human-like behavior.
        
        Args:
            element: Playwright locator
            description: Description for logging
            
        Returns:
            True if successful
        """
        try:
            logger.debug(f"Scrolling to {description}...")
            
            # Check if already visible
            if element.is_visible():
                return True
            
            # Scroll into view
            element.scroll_into_view_if_needed()
            time.sleep(random.uniform(0.3, 0.6))
            return True
            
        except Exception as e:
            logger.warning(f"Scroll to element failed: {e}")
            return False
    
    def wait_and_tap(self, element, description: str = "element", timeout: int = 10000) -> bool:
        """
        Wait for element to be visible then tap.
        
        Args:
            element: Playwright locator
            description: Description for logging
            timeout: Max time to wait in ms
            
        Returns:
            True if successful
        """
        try:
            element.wait_for(state="visible", timeout=timeout)
            return self.tap(element, description)
        except Exception as e:
            logger.warning(f"Wait and tap failed for {description}: {e}")
            return False

    def hold(self, element, duration: float = 10.0, description: str = "element") -> bool:
        """
        Press and hold an element (for CAPTCHA).
        
        Args:
            element: Playwright locator
            duration: Duration in seconds
            description: Description for logging
            
        Returns:
            True if successful
        """
        try:
            logger.info(f"Holding {description} for {duration}s...")
            
            # Scroll into view
            self.scroll_to_element(element, description)
            time.sleep(0.5)
            
            # Use click with delay to simulate hold
            # Convert seconds to ms
            delay_ms = duration * 1000
            
            # Add some randomness to duration
            actual_delay = delay_ms + random.uniform(-1000, 1000)
            if actual_delay < 1000: actual_delay = 1000
            
            # Perform hold
            element.click(delay=actual_delay, force=True)
            return True
            
        except Exception as e:
            logger.warning(f"Hold failed for {description}: {e}")
            return False

    def js_click(self, element, description: str = "element") -> bool:
        """
        Perform a JavaScript click on the element.
        This is often more reliable than standard clicks for stubborn elements.
        
        Args:
            element: Playwright locator
            description: Description for logging
            
        Returns:
            True if successful
        """
        try:
            if self.page.is_closed():
                logger.error("Page closed. Cannot JS click.")
                return False
            
            logger.info(f"⚡ Executing JS click on {description}...")
            
            # Ensure element is resolved
            if not element.count():
                element.wait_for(state="attached", timeout=5000)
                
            element.evaluate("el => el.click()")
            return True
        except Exception as e:
            logger.warning(f"JS click failed for {description}: {e}")
            return False
