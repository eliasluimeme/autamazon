"""
Date of Birth Step Handler for Outlook Signup

Strategy (3-tier):
  1. Cached XPath selectors  (fastest — from data/xpath_cache/outlook_selectors.json)
  2. CSS selectors            (fast — browser-native querySelector)
  3. AgentQL fallback          (slow but robust — extracts & caches XPaths for next run)
"""

import time
import random
from loguru import logger

from amazon.outlook.selectors import SELECTORS
from amazon.outlook.config import DELAYS
from amazon.outlook.utils.xpath_cache import (
    find_element,
    extract_and_cache_xpath,
    get_cached_xpath,
    DOMPATH_AVAILABLE,
)


def handle_dob_step(page, identity: dict, device, agentql_page=None) -> bool:
    """
    Handle the date of birth selection step.

    Args:
        page: Playwright page
        identity: Dict (may optionally contain dob, else random)
        device: DeviceAdapter instance
        agentql_page: Optional AgentQL-wrapped page

    Returns:
        True if step completed successfully
    """
    logger.info("📅 Handling DOB step")

    # Priority 0: Try cached selectors (fastest)
    try:
        success = _handle_via_cache(page, device)
        if success:
            logger.success("✅ DOB step completed via cached selectors")
            return True
    except Exception as e:
        logger.debug(f"Cached selector approach failed: {e}")

    # Priority 1: Try CSS selectors
    try:
        success = _handle_via_selectors(page, device)
        if success:
            logger.success("✅ DOB step completed via CSS selectors")
            return True
    except Exception as e:
        logger.debug(f"CSS selector approach failed: {e}")

    # Priority 2: AgentQL fallback (most robust)
    if agentql_page:
        try:
            success = _handle_via_agentql(page, agentql_page, device)
            if success:
                return True
        except Exception as e:
            logger.warning(f"AgentQL approach failed: {e}")

    logger.error("DOB step failed")
    return False


# ---------------------------------------------------------------------------
# Tier 0: Cached XPaths (via find_element)
# ---------------------------------------------------------------------------

def _handle_via_cache(page, device) -> bool:
    """Try using cached XPaths from previous successful runs."""
    day_el = find_element(page, "dob_day", timeout=3000)
    month_el = find_element(page, "dob_month", timeout=2000)
    year_el = find_element(page, "dob_year", timeout=2000)

    if not all([day_el, month_el, year_el]):
        logger.debug("Not all DOB selectors found in cache, skipping cache approach")
        return False

    logger.info("🔄 Attempting DOB via cached selectors...")

    try:
        # Day
        success = _interact_with_dropdown(page, day_el, "Day (cached)", device, 1, 28)
        if not success:
            logger.warning("Cached day selector interaction failed")
            return False
        time.sleep(0.3)

        # Month
        success = _interact_with_dropdown(page, month_el, "Month (cached)", device, 1, 12)
        if not success:
            logger.warning("Cached month selector interaction failed")
            return False
        time.sleep(0.3)

        # Year - text input
        year_val = str(random.randint(1980, 2005))
        year_el.fill("")
        time.sleep(0.1)
        device.type_text(year_el, year_val, "year (cached)")
        logger.debug(f"✅ Entered year: {year_val}")

        time.sleep(0.5)

        # Next button (try cache first, then CSS fallback)
        next_btn = find_element(page, "dob_next", timeout=2000,
                                css_fallback=SELECTORS["dob"]["next_button"])
        if next_btn:
            device.js_click(next_btn, "next button (cached)")
            time.sleep(1.0)

            if _check_for_error(page):
                logger.warning("Error detected after DOB submit (cached)")
                return False

            return True
        else:
            logger.warning("Cached next button not visible")

    except Exception as e:
        logger.debug(f"Cache approach error: {e}")

    return False


# ---------------------------------------------------------------------------
# Tier 1: CSS Selectors
# ---------------------------------------------------------------------------

def _handle_via_selectors(page, device) -> bool:
    """Handle DOB step using CSS selectors from selectors.py."""
    logger.info("🔍 Attempting DOB via CSS selectors...")

    # Day dropdown
    day_el = page.locator(SELECTORS["dob"]["day_select"]).first
    if not day_el.is_visible(timeout=3000):
        logger.debug("Day element not visible via CSS")
        return False

    success = _interact_with_dropdown(page, day_el, "Day (CSS)", device, 1, 28)
    if not success:
        return False
    time.sleep(0.3)

    # Month dropdown
    month_el = page.locator(SELECTORS["dob"]["month_select"]).first
    if not month_el.is_visible(timeout=2000):
        logger.debug("Month element not visible via CSS")
        return False

    success = _interact_with_dropdown(page, month_el, "Month (CSS)", device, 1, 12)
    if not success:
        return False
    time.sleep(0.3)

    # Year input
    year_el = page.locator(SELECTORS["dob"]["year_input"]).first
    if not year_el.is_visible(timeout=2000):
        logger.debug("Year element not visible via CSS")
        return False

    year_val = str(random.randint(1980, 2005))
    year_el.fill("")
    time.sleep(0.1)
    device.type_text(year_el, year_val, "year (CSS)")
    logger.debug(f"✅ Entered year: {year_val}")

    time.sleep(0.5)

    # Next button
    next_btn = page.locator(SELECTORS["dob"]["next_button"]).first
    if next_btn.is_visible(timeout=2000):
        device.js_click(next_btn, "next button (CSS)")
        time.sleep(1.0)

        if _check_for_error(page):
            logger.warning("Error detected after DOB submit (CSS)")
            return False

        return True

    return False


# ---------------------------------------------------------------------------
# Tier 2: AgentQL fallback (extracts & caches XPaths)
# ---------------------------------------------------------------------------

def _handle_via_agentql(page, agentql_page, device) -> bool:
    """Handle DOB step using AgentQL with XPath extraction and caching."""
    import agentql

    # Try to import playwright-dompath for XPath extraction
    try:
        from playwright_dompath.dompath_sync import xpath_path
        dompath_ok = True
    except ImportError:
        dompath_ok = False
        logger.warning("playwright-dompath not installed, XPath caching disabled")

    logger.info("🧠 Attempting AgentQL fallback for DOB...")

    # Use a more descriptive query
    DOB_QUERY = """
    {
        day_dropdown(clickable dropdown or button to select day of birth)
        month_dropdown(clickable dropdown or button to select month of birth)
        year_input(text input field for birth year)
        next_button(button to proceed to next step)
    }
    """

    try:
        aq_page = agentql_page if agentql_page else agentql.wrap(page)
        response = aq_page.query_elements(DOB_QUERY)

        # Debug: Log what AgentQL found
        logger.debug(f"AgentQL response attributes: {[a for a in dir(response) if not a.startswith('_')]}")

        has_day = response.day_dropdown is not None
        has_month = response.month_dropdown is not None
        has_year = response.year_input is not None
        has_next = response.next_button is not None

        logger.debug(f"Found elements - Day: {has_day}, Month: {has_month}, Year: {has_year}, Next: {has_next}")

        if not response.year_input:
            logger.warning("AgentQL could not find birth year input")
            return False

        # Extract and cache XPaths if available
        if dompath_ok:
            try:
                if response.day_dropdown:
                    extract_and_cache_xpath(response.day_dropdown, "dob_day", {"step": "dob"})
                if response.month_dropdown:
                    extract_and_cache_xpath(response.month_dropdown, "dob_month", {"step": "dob"})
                if response.year_input:
                    extract_and_cache_xpath(response.year_input, "dob_year", {"step": "dob"})
                if response.next_button:
                    extract_and_cache_xpath(response.next_button, "dob_next", {"step": "dob"})
            except Exception as e:
                logger.warning(f"XPath extraction failed: {e}")

        # Handle Day dropdown
        if response.day_dropdown:
            logger.debug("📅 Processing Day dropdown...")
            try:
                success = _interact_with_agentql_dropdown(
                    page, response.day_dropdown, "Day", device, 1, 28
                )
                if not success:
                    logger.warning("Day dropdown interaction returned False")
            except Exception as e:
                logger.warning(f"Day dropdown processing failed: {e}")
        else:
            logger.warning("No day_dropdown element found by AgentQL")

        time.sleep(0.3)

        # Handle Month dropdown
        if response.month_dropdown:
            logger.debug("📅 Processing Month dropdown...")
            try:
                success = _interact_with_agentql_dropdown(
                    page, response.month_dropdown, "Month", device, 1, 12
                )
                if not success:
                    logger.warning("Month dropdown interaction returned False")
            except Exception as e:
                logger.warning(f"Month dropdown processing failed: {e}")
        else:
            logger.warning("No month_dropdown element found by AgentQL")

        time.sleep(0.3)

        # Handle Year input
        if response.year_input:
            logger.debug("📅 Processing Year input...")
            try:
                year_val = str(random.randint(1980, 2005))
                response.year_input.scroll_into_view_if_needed()
                time.sleep(0.2)

                response.year_input.fill("")
                time.sleep(0.1)
                device.type_text(response.year_input, year_val, "year input (AgentQL)")
                logger.debug(f"✅ Entered year: {year_val}")
            except Exception as e:
                logger.warning(f"Year input interaction failed: {e}")

        time.sleep(random.uniform(0.5, 1.0))

        # Click Next button
        if response.next_button:
            logger.debug("📅 Clicking Next button...")
            try:
                response.next_button.scroll_into_view_if_needed()
                time.sleep(0.3)
                device.js_click(response.next_button, "next button (AgentQL)")

                time.sleep(1.5)
                if _check_for_error(page):
                    logger.warning("Error detected after DOB submit via AgentQL")
                    return False

                time.sleep(random.uniform(1.0, 2.0))
                return True
            except Exception as e:
                logger.error(f"Failed to click next button: {e}")
                return False

        return False

    except Exception as e:
        logger.error(f"AgentQL DOB handling failed: {e}")
        import traceback
        logger.debug(traceback.format_exc())
        return False


# ---------------------------------------------------------------------------
# Dropdown interaction helpers
# ---------------------------------------------------------------------------

def _interact_with_dropdown(page, element, description: str, device, min_val: int, max_val: int) -> bool:
    """
    Interact with a dropdown that requires click-to-open behavior.
    Handles both native <select> and custom dropdowns.
    """
    logger.debug(f"🔷 Interacting with dropdown: {description}")

    try:
        tag_name = element.evaluate("el => el.tagName.toLowerCase()")
        class_name = element.evaluate("el => el.className || ''")
        aria_expanded = element.evaluate("el => el.getAttribute('aria-expanded')")
        logger.debug(f"  Tag: {tag_name}, Class: {class_name[:50]}..., aria-expanded: {aria_expanded}")

        role = element.evaluate("el => el.getAttribute('role')")
        logger.debug(f"  Role: {role}")

        # Strategy 1: Native select
        if tag_name == "select":
            logger.debug(f"  → Using native select strategy")
            option_count = element.evaluate("el => el.options.length")
            if option_count > 1:
                val = str(random.randint(min_val, min(max_val, option_count - 1)))
                element.select_option(value=val)
                logger.debug(f"  ✅ Native select: selected value {val}")
                return True

        # Strategy 2: Click to open dropdown
        logger.debug(f"  → Clicking to open dropdown")
        element.scroll_into_view_if_needed()
        time.sleep(0.2)

        device.js_click(element, f"{description} dropdown trigger")
        time.sleep(0.5)

        # Look for dropdown options
        dropdown_options = None

        option_selectors = [
            "[role='option']",
            "[role='listbox'] > *",
            "[role='menu'] > *",
            "li[data-value]",
            ".dropdown-item",
            "button[data-value]",
            "[class*='option']",
        ]

        for selector in option_selectors:
            try:
                options = page.locator(selector).locator("visible=true")
                count = options.count()
                if count > 0:
                    logger.debug(f"  Found {count} visible options with selector: {selector}")
                    dropdown_options = options
                    break
            except Exception:
                pass

        if dropdown_options and dropdown_options.count() > 0:
            opt_count = dropdown_options.count()
            random_idx = random.randint(0, min(opt_count - 1, max_val - min_val))

            try:
                option = dropdown_options.nth(random_idx)
                option_text = option.text_content().strip()
                logger.debug(f"  Selecting option {random_idx}: '{option_text}'")

                initial_text = element.text_content().strip()

                device.js_click(option, f"option {random_idx}")
                time.sleep(0.5)

                current_text = element.text_content().strip()
                if current_text != initial_text or current_text == option_text:
                    logger.debug(f"  ✅ Verification: Dropdown text changed ('{initial_text}' -> '{current_text}')")
                    return True

                logger.warning(f"  ⚠️ Text didn't change after JS click. Retrying with standard click...")
                try:
                    option.scroll_into_view_if_needed()
                    option.click(force=True)
                    time.sleep(0.5)

                    if element.text_content().strip() != initial_text:
                        logger.debug("  ✅ Verification: Dropdown text changed after standard click")
                        return True
                except Exception as e:
                    logger.warning(f"  Standard click retry failed: {e}")

                return False
            except Exception as e:
                logger.warning(f"  Failed to click option: {e}")
                return False
        else:
            logger.debug("  No dropdown options found, trying input fallback")

        return False

    except Exception as e:
        logger.error(f"  ❌ Dropdown interaction failed: {e}")
        return False


def _interact_with_agentql_dropdown(page, element, name: str, device, min_val: int, max_val: int) -> bool:
    """
    Interact with a dropdown element found by AgentQL.
    Handles click-to-open dropdowns common in modern web apps.
    """
    logger.debug(f"🔷 AgentQL dropdown interaction: {name}")

    try:
        tag_name = element.evaluate("el => el.tagName.toLowerCase()")
        outer_html = element.evaluate("el => el.outerHTML.substring(0, 200)")
        logger.debug(f"  Element tag: {tag_name}")
        logger.debug(f"  HTML preview: {outer_html}")

        current_text = element.evaluate("el => el.textContent || el.value || ''")
        logger.debug(f"  Current text: '{current_text.strip()}'")

        element.scroll_into_view_if_needed()
        time.sleep(0.2)

        # Strategy 1: Native select
        if tag_name == "select":
            option_count = element.evaluate("el => el.options.length")
            logger.debug(f"  Native select with {option_count} options")
            if option_count > 1:
                val = str(random.randint(min_val, min(max_val, option_count - 1)))
                element.select_option(value=val)
                logger.debug(f"  ✅ Selected value: {val}")
                return True

        # Strategy 2: Click to open dropdown menu
        logger.debug(f"  Clicking {name} to open dropdown...")
        device.js_click(element, f"{name} dropdown")
        time.sleep(0.6)

        option_found = False

        option_selectors = [
            "[role='option']:visible",
            "[role='listbox'] [role='option']",
            "[role='menu'] button",
            "[role='menuitem']",
            "li[role='option']",
            "[data-value]",
            ".select-option",
            ".dropdown-option",
            "ul:visible > li",
            "div[class*='dropdown'] button",
            "div[class*='listbox'] > div",
        ]

        for selector in option_selectors:
            try:
                options = page.locator(selector)
                count = options.count()
                if count > 1:
                    logger.debug(f"  Found {count} options with: {selector}")

                    visible_count = 0
                    for i in range(min(count, 35)):
                        try:
                            if options.nth(i).is_visible(timeout=100):
                                visible_count += 1
                        except Exception:
                            pass

                    if visible_count > 0:
                        logger.debug(f"  {visible_count} visible options")

                        target_idx = random.randint(1, min(visible_count - 1, max_val))

                        visible_idx = 0
                        for i in range(count):
                            try:
                                opt = options.nth(i)
                                if opt.is_visible(timeout=100):
                                    if visible_idx == target_idx:
                                        opt_text = opt.text_content()
                                        logger.debug(f"  Selecting option {target_idx}: '{opt_text.strip()}'")
                                        initial_text = element.text_content().strip()

                                        device.js_click(opt, f"option {target_idx}")
                                        time.sleep(0.5)

                                        current_text = element.text_content().strip()
                                        if current_text != initial_text or current_text == opt_text:
                                            logger.debug(f"  ✅ Verification: AgentQL Text changed ('{initial_text}' -> '{current_text}')")
                                            option_found = True
                                            break

                                        logger.warning(f"  ⚠️ AgentQL text didn't change. Retrying with force click...")
                                        try:
                                            opt.click(force=True)
                                            time.sleep(0.5)
                                            if element.text_content().strip() != initial_text:
                                                logger.debug("  ✅ Verification: AgentQL text changed after force click")
                                                option_found = True
                                                break
                                        except Exception as e:
                                            logger.warning(f"  Retry click failed: {e}")

                                    visible_idx += 1
                            except Exception:
                                pass

                        if option_found:
                            break
            except Exception as e:
                logger.debug(f"  Selector {selector} failed: {e}")
                continue

        if option_found:
            logger.debug(f"  ✅ Successfully selected {name} option")
            return True
        else:
            logger.warning(f"  ❌ Could not find/select {name} dropdown options")
            try:
                page.keyboard.press("Escape")
                time.sleep(0.2)
            except Exception:
                pass
            return False

    except Exception as e:
        logger.error(f"  ❌ AgentQL dropdown interaction error: {e}")
        import traceback
        logger.debug(traceback.format_exc())
        return False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _check_for_error(page) -> bool:
    """Check if there's an error message on the page. Returns True if error found."""
    try:
        error_selectors = [
            ".alert-error",
            ".error",
            "[role='alert']",
            ":text('Enter your birthdate')",
            ":text('Please enter')",
            "#errorMessage",
        ]

        for selector in error_selectors:
            try:
                if page.locator(selector).first.is_visible(timeout=500):
                    error_text = page.locator(selector).first.text_content()
                    logger.debug(f"Error found with '{selector}': {error_text}")
                    return True
            except Exception:
                pass

        return False
    except Exception:
        return False
