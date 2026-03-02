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

    # Priority 0: Try cached selectors (fastest & avoid AgentQL limits)
    try:
        success = _handle_via_cache(page, device)
        if success:
            logger.success("✅ DOB step completed via cached selectors")
            return True
    except Exception as e:
        logger.debug(f"Cached selector approach failed: {e}")

    # Priority 1: AgentQL (if available)
    if agentql_page:
        try:
            success = _handle_via_agentql(page, agentql_page, device)
            if success:
                logger.success("✅ DOB step completed via AgentQL")
                return True
        except Exception as e:
            if "API Key limit" in str(e):
                logger.warning("⚠️ AgentQL API limit reached - skipping")
            else:
                logger.warning(f"AgentQL approach failed: {e}")

    # Priority 2: Try CSS selectors
    try:
        success = _handle_via_selectors(page, device)
        if success:
            logger.success("✅ DOB step completed via CSS selectors")
            return True
    except Exception as e:
        logger.debug(f"CSS selector approach failed: {e}")

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
        year_val = str(random.randint(1960, 2000))
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

    # Use a more descriptive query that focuses on the specific dropdowns
    DOB_QUERY = """
    {
        day_dropdown(button with aria-label "Birth day" or id "BirthDayDropdown")
        month_dropdown(button with aria-label "Birth month" or id "BirthMonthDropdown")
        year_input(input for birth year or id "BirthYear")
        next_button(the next button or submit button)
    }
    """

    try:
        aq_page = agentql_page if agentql_page else agentql.wrap(page)
        response = aq_page.query_elements(DOB_QUERY)

        # Extract and cache XPaths early for robustness
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
                logger.warning(f"XPath extraction/caching failed: {e}")

        # Handle Day dropdown
        if response.day_dropdown:
            logger.debug("📅 Processing Day dropdown via AgentQL...")
            day_val = str(random.randint(1, 28))
            # Use query for a specific option for robustness
            DAY_OPTION_QUERY = f'{{ option(the option with text "{day_val}") }}'
            
            try:
                response.day_dropdown.tap(force=True, timeout=2000)
                time.sleep(1.2)
                
                # Try to find specific option via AgentQL first
                opt_response = aq_page.query_elements(DAY_OPTION_QUERY)
                if opt_response.option:
                    device.js_click(opt_response.option, f"Day option {day_val}")
                    success = True
                else:
                    # Fallback to robust discovery
                    success = _interact_with_agentql_dropdown(
                        page, response.day_dropdown, "Day", device, 1, 28
                    )
                
                if not success:
                    logger.warning("Day dropdown interaction failed")
                    return False
            except Exception as e:
                logger.warning(f"Day dropdown processing failed: {e}")
                return False
        else:
            logger.warning("No day_dropdown element found by AgentQL")

        time.sleep(0.3)

        # Handle Month dropdown
        if response.month_dropdown:
            logger.debug("📅 Processing Month dropdown via AgentQL...")
            month_idx = random.randint(1, 12)
            # Use query with index or descriptive name
            MONTH_OPTION_QUERY = f'{{ option(the {month_idx}th item in the list) }}'
            
            try:
                response.month_dropdown.tap(force=True, timeout=2000)
                time.sleep(1.2)
                
                opt_response = aq_page.query_elements(MONTH_OPTION_QUERY)
                if opt_response.option:
                    device.js_click(opt_response.option, f"Month option {month_idx}")
                    success = True
                else:
                    success = _interact_with_agentql_dropdown(
                        page, response.month_dropdown, "Month", device, 1, 12
                    )
                
                if not success:
                    logger.warning("Month dropdown interaction failed")
                    return False
            except Exception as e:
                logger.warning(f"Month dropdown processing failed: {e}")
                return False
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
        time.sleep(0.3)

        dropdown_opened = False
        
        # Attempt 1: Playwright .tap() — fires proper touch events on mobile
        try:
            element.tap(force=True, timeout=2000)
            time.sleep(1.0)
            aria_state = element.evaluate("el => el.getAttribute('aria-expanded')")
            if aria_state == "true":
                dropdown_opened = True
                logger.debug(f"  ✅ Dropdown opened via tap()")
        except Exception as e:
            logger.debug(f"  tap() failed: {e}")

        # Attempt 2: JS focus + click — some Fluent UI components need focus first
        if not dropdown_opened:
            try:
                element.evaluate("""el => {
                    el.focus();
                    el.click();
                }""")
                time.sleep(1.0)
                aria_state = element.evaluate("el => el.getAttribute('aria-expanded')")
                if aria_state == "true":
                    dropdown_opened = True
                    logger.debug(f"  ✅ Dropdown opened via focus+click")
            except Exception as e:
                logger.debug(f"  focus+click failed: {e}")

        # Attempt 3: JS PointerEvent dispatch (for touch devices)
        if not dropdown_opened:
            try:
                element.evaluate("""el => {
                    const rect = el.getBoundingClientRect();
                    const x = rect.left + rect.width / 2;
                    const y = rect.top + rect.height / 2;
                    ['pointerdown', 'pointerup', 'click'].forEach(evt => {
                        el.dispatchEvent(new PointerEvent(evt, {
                            view: window, bubbles: true, cancelable: true,
                            pointerType: 'touch', isPrimary: true,
                            clientX: x, clientY: y
                        }));
                    });
                }""")
                time.sleep(1.0)
                aria_state = element.evaluate("el => el.getAttribute('aria-expanded')")
                if aria_state == "true":
                    dropdown_opened = True
                    logger.debug(f"  ✅ Dropdown opened via PointerEvent")
            except Exception as e:
                logger.debug(f"  PointerEvent dispatch failed: {e}")

        # Attempt 4: device.js_click as last resort
        if not dropdown_opened:
            device.js_click(element, f"{description} dropdown trigger")
            time.sleep(1.0)
            try:
                aria_state = element.evaluate("el => el.getAttribute('aria-expanded')")
                if aria_state == "true":
                    dropdown_opened = True
                    logger.debug(f"  ✅ Dropdown opened via js_click")
            except:
                pass

        if not dropdown_opened:
            logger.warning(f"  ⚠️ Dropdown may not have opened (aria-expanded != true)")
            # Continue anyway — options might still be discoverable

        time.sleep(0.5)

        # Look for dropdown options
        visible_options = []
        option_selectors = [
            "[role='option']",
            "[role='listbox'] [role='option']",
            ".fui-Option",
            ".fui-ListBox [role='option']",
            "li[role='option']",
            ".dropdown-item",
            "[class*='option']",
            "div[role='listbox'] > div",
            "ul[role='listbox'] > li",
            # Broad fallbacks
            "button:visible",
            "li:visible",
            "div[role='button']:visible"
        ]

        # Sometimes the listbox is outside the container, search globally
        for selector in option_selectors:
            try:
                loc = page.locator(selector)
                count = loc.count()
                for i in range(count):
                    opt = loc.nth(i)
                    # Be very lenient with visibility for custom menus
                    if opt.is_visible() or opt.evaluate("el => el.offsetHeight > 0"):
                        # If we have a range, filter by content if possible
                        text = (opt.text_content() or "").strip()
                        desc_lower = description.lower()
                        if "day" in desc_lower:
                            if text.isdigit() and 1 <= int(text) <= 31:
                                visible_options.append(opt)
                        elif "month" in desc_lower:
                            months = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
                            if text.isdigit() and 1 <= int(text) <= 12:
                                visible_options.append(opt)
                            elif any(m in text.lower() for m in months):
                                visible_options.append(opt)
                        else:
                            visible_options.append(opt)
                
                if len(visible_options) > 0:
                    logger.debug(f"  Found {len(visible_options)} candidates with: {selector}")
                    break
            except Exception:
                continue

        # Strategy 3: Blind global fallback
        if not visible_options:
            logger.debug("  → Strategy 3: Blind search for numeric/month items")
            try:
                # Search for any buttons or list items on page that look like the choices
                page_options = page.locator("button, li, [role='button'], .fui-Option").locator("visible=true")
                for i in range(page_options.count()):
                    opt = page_options.nth(i)
                    text = (opt.text_content() or "").strip()
                    desc_lower = description.lower()
                    if "day" in desc_lower and text.isdigit() and 1 <= int(text) <= 31:
                        visible_options.append(opt)
                    elif "month" in desc_lower:
                        months = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
                        if (text.isdigit() and 1 <= int(text) <= 12) or any(m in text.lower() for m in months):
                            visible_options.append(opt)
            except:
                pass

        if visible_options:
            # Random selection from available options
            idx = random.randint(1 if len(visible_options) > 5 else 0, len(visible_options) - 1)
            target_opt = visible_options[idx]

            try:
                opt_text = (target_opt.text_content() or "").strip()
                logger.debug(f"  Selecting option {idx}: '{opt_text}'")
                initial_text = (element.text_content() or "").strip()

                # Force JS click (requested)
                device.js_click(target_opt, f"option {idx}")
                time.sleep(1.2)

                current_text = (element.text_content() or "").strip()
                if current_text != initial_text or (opt_text and opt_text in current_text):
                    logger.debug(f"  ✅ Verification: Dropdown updated")
                    return True

                # Native force click fallback
                target_opt.click(force=True, timeout=2000)
                time.sleep(1.0)
                return True
            except Exception as e:
                logger.warning(f"  Failed selection: {e}")
                return False
        
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
        
        dropdown_opened = False
        
        # Attempt 1: Playwright .tap()
        try:
            element.tap(force=True, timeout=2000)
            time.sleep(1.0)
            aria_state = element.evaluate("el => el.getAttribute('aria-expanded')")
            if aria_state == "true":
                dropdown_opened = True
                logger.debug(f"  ✅ Dropdown opened via tap()")
        except Exception as e:
            logger.debug(f"  tap() failed: {e}")

        # Attempt 2: JS focus + click
        if not dropdown_opened:
            try:
                element.evaluate("""el => {
                    el.focus();
                    el.click();
                }""")
                time.sleep(1.0)
                aria_state = element.evaluate("el => el.getAttribute('aria-expanded')")
                if aria_state == "true":
                    dropdown_opened = True
                    logger.debug(f"  ✅ Dropdown opened via focus+click")
            except Exception as e:
                logger.debug(f"  focus+click failed: {e}")

        # Attempt 3: JS PointerEvent dispatch
        if not dropdown_opened:
            try:
                element.evaluate("""el => {
                    const rect = el.getBoundingClientRect();
                    const x = rect.left + rect.width / 2;
                    const y = rect.top + rect.height / 2;
                    ['pointerdown', 'pointerup', 'click'].forEach(evt => {
                        el.dispatchEvent(new PointerEvent(evt, {
                            view: window, bubbles: true, cancelable: true,
                            pointerType: 'touch', isPrimary: true,
                            clientX: x, clientY: y
                        }));
                    });
                }""")
                time.sleep(1.0)
                aria_state = element.evaluate("el => el.getAttribute('aria-expanded')")
                if aria_state == "true":
                    dropdown_opened = True
                    logger.debug(f"  ✅ Dropdown opened via PointerEvent")
            except Exception as e:
                logger.debug(f"  PointerEvent dispatch failed: {e}")

        # Attempt 4: device.js_click fallback
        if not dropdown_opened:
            device.js_click(element, f"{name} dropdown")
            time.sleep(1.0)

        if not dropdown_opened:
            logger.warning(f"  ⚠️ Dropdown may not have opened")

        time.sleep(0.5)

        option_found = False

        # Look for dropdown options
        visible_options = []
        option_selectors = [
            "[role='option']",
            "[role='listbox'] [role='option']",
            ".fui-Option",
            ".fui-ListBox [role='option']",
            "li[role='option']",
            ".dropdown-item",
            "[class*='option']",
            "div[role='listbox'] > div",
            "ul[role='listbox'] > li",
        ]

        for selector in option_selectors:
            try:
                loc = page.locator(selector)
                count = loc.count()
                for i in range(count):
                    opt = loc.nth(i)
                    # Lenient visibility
                    if opt.is_visible() or opt.evaluate("el => el.offsetHeight > 0"):
                        # Filter by content if possible
                        text = (opt.text_content() or "").strip()
                        if "day" in name.lower() and text.isdigit() and 1 <= int(text) <= 31:
                            visible_options.append(opt)
                        elif "month" in name.lower():
                            months = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
                            if (text.isdigit() and 1 <= int(text) <= 12) or any(m in text.lower() for m in months):
                                visible_options.append(opt)
                        else:
                            visible_options.append(opt)
                
                if len(visible_options) > 0:
                    logger.debug(f"  Found {len(visible_options)} candidates with: {selector}")
                    break
            except Exception:
                continue

        # Global fallback
        if not visible_options:
            try:
                page_options = page.locator("button, li, [role='button'], .fui-Option").locator("visible=true")
                for i in range(page_options.count()):
                    opt = page_options.nth(i)
                    text = (opt.text_content() or "").strip()
                    if "day" in name.lower() and text.isdigit() and 1 <= int(text) <= 31:
                        visible_options.append(opt)
                    elif "month" in name.lower():
                        months = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
                        if (text.isdigit() and 1 <= int(text) <= 12) or any(m in text.lower() for m in months):
                            visible_options.append(opt)
            except:
                pass

        if visible_options:
            # Selection
            idx = random.randint(1 if len(visible_options) > 5 else 0, len(visible_options) - 1)
            target_opt = visible_options[idx]
            
            opt_text = (target_opt.text_content() or "").strip()
            logger.debug(f"  Selecting option {idx}: '{opt_text}'")
            initial_text = (element.text_content() or "").strip()

            device.js_click(target_opt, f"option {idx}")
            time.sleep(1.2)

            current_text = (element.text_content() or "").strip()
            if current_text != initial_text or (opt_text and opt_text in current_text):
                logger.debug(f"  ✅ Verification: AgentQL Text changed")
                option_found = True
            else:
                # Force click fallback
                target_opt.click(force=True, timeout=2000)
                time.sleep(1.0)
                option_found = True
        
        if option_found:
            return True
        else:
            logger.warning(f"  ❌ Selection failed for {name}")
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
