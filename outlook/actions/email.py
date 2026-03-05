"""
Email Step Handler for Outlook Signup

Handles entering the email address / generating new username.

Strategy (3-tier):
  1. Cached XPath selectors  (fastest — from data/xpath_cache/outlook_selectors.json)
  2. CSS selectors            (fast — browser-native querySelector)
  3. AgentQL fallback          (slow but robust — extracts & caches XPaths for next run)
"""

import time
import random
from loguru import logger

from amazon.outlook.selectors import SELECTORS
from amazon.outlook.queries import EMAIL_STEP_QUERY
from amazon.outlook.config import DELAYS
from amazon.outlook.utils.xpath_cache import (
    find_element,
    extract_and_cache_xpath,
    get_cached_xpath,
    DOMPATH_AVAILABLE,
)


def _is_split_mode(page) -> bool:
    """
    Detect if the email form is in 'split mode' (handle input + domain dropdown).

    On desktop, the signup form at signup.live.com shows a text input for the
    handle and a SEPARATE dropdown for the domain (@outlook.com / @hotmail.com).
    Typing the full email (handle@outlook.com) into the handle-only input
    triggers a format error.

    Detection strategy (broadest first):
      1. JavaScript DOM inspection — look for any visible element showing
         '@outlook.com' or '@hotmail.com' that is NOT the email input itself.
      2. CSS selector fallback for known dropdown IDs.
      3. Page-content string search.
    """
    # ── Method 1: JS DOM evaluation (most robust) ────────────────────────
    try:
        result = page.evaluate("""() => {
            const input = document.querySelector('#MemberName, input[name="MemberName"]');
            if (!input) return false;
            const inputVal = (input.value || '').toLowerCase();

            // Scan select elements for domain options
            const selects = document.querySelectorAll('select');
            for (const sel of selects) {
                for (const opt of sel.options) {
                    const t = (opt.text || opt.value || '').toLowerCase();
                    if (t.includes('@outlook') || t.includes('@hotmail')) return true;
                }
            }

            // Scan buttons / comboboxes / dropdowns for domain text
            const candidates = document.querySelectorAll(
                'button, [role="combobox"], [role="listbox"], [role="option"]'
            );
            for (const el of candidates) {
                if (el === input) continue;
                const t = (el.textContent || '').trim().toLowerCase();
                if (t.includes('@outlook.com') || t.includes('@hotmail.com')) return true;
            }

            // Check the form container for visible @domain text
            // (walk up a few parents from the input)
            let container = input.parentElement;
            for (let i = 0; i < 6 && container; i++) {
                const kids = container.children;
                for (const kid of kids) {
                    if (kid === input || kid.contains(input)) continue;
                    const t = (kid.innerText || '').toLowerCase();
                    if (t.includes('@outlook.com') || t.includes('@hotmail.com')) return true;
                }
                container = container.parentElement;
            }

            return false;
        }""")
        if result:
            logger.debug("Split mode detected via JS DOM evaluation")
            return True
    except Exception as e:
        logger.debug(f"JS split-mode detection error: {e}")

    # ── Method 2: CSS selector for known dropdown IDs ────────────────────
    try:
        domain_dd = page.locator(SELECTORS["email"]["domain_dropdown"]).first
        if domain_dd.is_visible(timeout=600):
            logger.debug("Split mode detected via domain dropdown selector")
            return True
    except Exception:
        pass

    # ── Method 3: Page-content string search ─────────────────────────────
    try:
        content = page.content()
        markers = [
            'LiveDomainBoxList', 'DomainBoxList', 'domainBox',
            '@outlook.com</option', '@hotmail.com</option',
            'aria-label="domain"', 'aria-label="Domain"',
        ]
        if any(m in content for m in markers):
            logger.debug("Split mode detected via page content")
            return True
    except Exception:
        pass

    return False


def _check_and_handle_format_error(page, identity: dict, device) -> bool:
    """
    Detect the email format error ('Enter your email address in the format:
    someone@example.com') that occurs on desktop when the full email
    (handle@outlook.com) is typed into the split-mode handle-only input.

    If detected:
      1. Clear the input
      2. Re-type ONLY the handle (without @outlook.com)
      3. Click Next
      4. Return True so the caller knows the error was recovered

    Returns:
        True  — format error was detected AND successfully recovered
        False — no format error found (caller should proceed normally)
    """
    format_error_found = False

    # Method 1: Check error element
    try:
        error_el = page.locator(SELECTORS["email"]["format_error"]).first
        if error_el.is_visible(timeout=800):
            error_text = error_el.inner_text(timeout=500).lower()
            if "format" in error_text or "someone@example" in error_text or "email address" in error_text:
                format_error_found = True
    except Exception:
        pass

    # Method 2: Check page content for error text
    if not format_error_found:
        try:
            content = page.content().lower()
            if ("enter your email address in the format" in content
                    or "someone@example.com" in content):
                format_error_found = True
        except Exception:
            pass

    # Method 3: Check if the input value contains '@' while in split mode
    # (the typed value shouldn't contain '@' in split mode)
    if not format_error_found:
        try:
            email_input = page.locator(SELECTORS["email"]["input"]).first
            if email_input.is_visible(timeout=500):
                val = email_input.input_value()
                if "@" in val and _is_split_mode(page):
                    logger.debug(f"Input contains '@' in split mode (value: {val})")
                    format_error_found = True
        except Exception:
            pass

    if not format_error_found:
        return False

    logger.warning("⚠️ Email format error detected (typed full email in split-mode input). Recovering...")

    try:
        email_input = page.locator(SELECTORS["email"]["input"]).first
        if not email_input.is_visible(timeout=1500):
            logger.error("Cannot find email input to recover from format error")
            return False

        # Clear and retype handle only
        email_input.fill("")
        time.sleep(0.3)
        handle = identity["email_handle"]
        logger.info(f"Re-typing handle only: {handle}")
        device.type_text(email_input, handle, "email input (format-error recovery)")
        time.sleep(random.uniform(*DELAYS["after_input"]))

        # Click Next
        next_btn = page.locator(SELECTORS["email"]["next_button"]).first
        if next_btn.is_visible(timeout=2000):
            device.js_click(next_btn, "next button (format-error recovery)")
            time.sleep(2)

            # Check if username was taken after recovery
            _check_and_handle_username_taken(page, identity, device)
            time.sleep(random.uniform(*DELAYS["step_transition"]))
            return True
    except Exception as e:
        logger.error(f"Format error recovery failed: {e}")

    return False


def handle_email_step(page, identity: dict, device, agentql_page=None, retry_count: int = 0) -> bool:
    """
    Handle the email input step.

    Flow:
    1. Check if "Get new email" link exists and click it
    2. Enter email handle (without @outlook.com if link clicked)
    3. Click Next button
    4. Check for errors (Already taken) -> Handle by picking suggestion or rotating identity

    Args:
        page: Playwright page
        identity: Dict with email_handle, password, etc.
        device: DeviceAdapter instance
        agentql_page: Optional AgentQL-wrapped page
        retry_count: Number of times we've retried this step

    Returns:
        True if step completed successfully
    """
    logger.info(f"📧 Handling EMAIL step (retry: {retry_count})")

    # Priority 0: Try cached selectors (self-healing)
    try:
        success = _handle_via_cache(page, identity, device, retry_count)
        if success:
            logger.success("✅ EMAIL step completed via cached selectors")
            return True
    except Exception as e:
        logger.debug(f"Cached selector approach failed: {e}")

    # Priority 1: Try CSS selectors
    try:
        success = _handle_via_selectors(page, identity, device, retry_count)
        if success:
            return True
    except Exception as e:
        logger.debug(f"Selector approach failed: {e}")

    # Priority 2: AgentQL fallback with XPath extraction
    if agentql_page:
        try:
            success = _handle_via_agentql(page, agentql_page, identity, device)
            if success:
                return True
        except Exception as e:
            logger.warning(f"AgentQL approach failed: {e}")

    logger.error("Email step failed with all approaches")
    return False


# ---------------------------------------------------------------------------
# Tier 0: Cached XPaths (via find_element)
# ---------------------------------------------------------------------------

def _handle_via_cache(page, identity: dict, device, retry_count: int) -> bool:
    """Try using cached XPaths from previous successful runs."""
    cached_input_el = find_element(page, "email_input", timeout=3000)
    if not cached_input_el:
        logger.debug("Email input not found in cache, skipping cache approach")
        return False

    logger.info("🔄 Attempting EMAIL via cached selectors...")

    try:
        is_split_mode = False

        # Check for "Get a new email address" link (via cache)
        new_link_el = find_element(page, "email_new_link", timeout=2000)
        if new_link_el:
            try:
                logger.debug("Clicking 'Get a new email address' link (cached)...")
                device.tap(new_link_el, "new email link (cached)")
                time.sleep(random.uniform(*DELAYS["after_click"]))
                is_split_mode = True
            except Exception:
                pass

        # Even if we didn't click the link, the form may already be in split
        # mode (e.g. retrying after "username taken"). Detect via dropdown.
        if not is_split_mode:
            is_split_mode = _is_split_mode(page)

        # Check for existing error and suggestions before typing
        if _check_and_handle_username_taken(page, identity, device):
            return True

        # Re-find input after potential page change
        email_input = find_element(page, "email_input", timeout=3000)
        if not email_input:
            logger.warning("Cached email input selector no longer works")
            return False

        # Determine what to type
        email_to_type = identity["email_handle"]
        if not is_split_mode:
            email_to_type = f"{identity['email_handle']}@outlook.com"

        logger.info(f"Typing email (cached): {email_to_type} (split mode: {is_split_mode})")

        # Clear and type
        email_input.fill("")
        time.sleep(0.2)
        device.type_text(email_input, email_to_type, "email input (cached)")

        time.sleep(random.uniform(*DELAYS["after_input"]))

        # Click next button
        next_btn = find_element(page, "email_next", timeout=2000,
                                css_fallback=SELECTORS["email"]["next_button"])
        if next_btn:
            device.js_click(next_btn, "next button (cached)")
            time.sleep(2)

            # Check for email format error (full email typed in split-mode input)
            if _check_and_handle_format_error(page, identity, device):
                return True

            if _check_and_handle_username_taken(page, identity, device):
                return True

            time.sleep(random.uniform(*DELAYS["step_transition"]))
            return True

    except Exception as e:
        logger.debug(f"Cache approach error: {e}")

    return False


# ---------------------------------------------------------------------------
# Tier 1: CSS Selectors
# ---------------------------------------------------------------------------

def _handle_via_selectors(page, identity: dict, device, retry_count: int) -> bool:
    """Handle email step using CSS selectors."""

    is_split_mode = False

    # Check for "Get a new email address" link
    try:
        new_email_link = page.locator(SELECTORS["email"]["new_email_link"]).first
        if new_email_link.is_visible(timeout=2000):
            logger.debug("Clicking 'Get a new email address' link...")
            device.tap(new_email_link, "new email link")
            time.sleep(random.uniform(*DELAYS["after_click"]))
            is_split_mode = True
    except Exception:
        pass

    # Even if we didn't click the link, the form may already be in split
    # mode (e.g. retrying after "username taken"). Detect via dropdown.
    if not is_split_mode:
        is_split_mode = _is_split_mode(page)

    # Check for existing error and suggestions before typing
    if _check_and_handle_username_taken(page, identity, device):
        return True

    # Find email input
    email_input = page.locator(SELECTORS["email"]["input"]).first
    if not email_input.is_visible(timeout=3000):
        return False

    # Determine what to type
    email_to_type = identity["email_handle"]
    if not is_split_mode:
        email_to_type = f"{identity['email_handle']}@outlook.com"

    # Check if already typed (likely from cached attempt)
    try:
        current_value = email_input.input_value()
        logger.debug(f"Checking existing input value: '{current_value}' against '{identity['email_handle']}'")

        # Relaxed check: if username is there, assume it's good
        if current_value and identity["email_handle"] in current_value:
            logger.info(f"✅ Email already typed ({current_value}), skipping typing.")

            # Just click next
            next_btn = page.locator(SELECTORS["email"]["next_button"]).first
            if next_btn.is_visible(timeout=2000):
                device.js_click(next_btn, "next button")
                time.sleep(2)
                if _check_and_handle_format_error(page, identity, device):
                    return True
                if _check_and_handle_username_taken(page, identity, device):
                    return True
                time.sleep(random.uniform(*DELAYS["step_transition"]))
                return True
    except Exception as e:
        logger.debug(f"Error checking input value: {e}")

    logger.info(f"Typing email: {email_to_type} (split mode: {is_split_mode})")

    # Clear and type
    email_input.fill("")
    time.sleep(0.2)
    device.type_text(email_input, email_to_type, "email input")

    time.sleep(random.uniform(*DELAYS["after_input"]))

    # Click next button
    next_btn = page.locator(SELECTORS["email"]["next_button"]).first
    if next_btn.is_visible(timeout=2000):
        device.js_click(next_btn, "next button")

        # Wait and check for error/suggestions
        time.sleep(2)

        # Check for email format error (full email typed in split-mode input)
        if _check_and_handle_format_error(page, identity, device):
            return True

        # Check if username was taken and handle
        if _check_and_handle_username_taken(page, identity, device):
            return True

        time.sleep(random.uniform(*DELAYS["step_transition"]))
        return True

    return False


# ---------------------------------------------------------------------------
# Tier 2: AgentQL fallback (extracts & caches XPaths)
# ---------------------------------------------------------------------------

def _handle_via_agentql(page, agentql_page, identity: dict, device) -> bool:
    """Handle email step using AgentQL with XPath extraction and caching."""
    logger.info("🧠 Attempting AgentQL fallback for EMAIL...")

    response = agentql_page.query_elements(EMAIL_STEP_QUERY)

    is_split_mode = False

    # Check for new email link
    if response.new_email_link:
        try:
            # Cache the new email link XPath
            if DOMPATH_AVAILABLE:
                try:
                    extract_and_cache_xpath(response.new_email_link, "email_new_link", {"step": "email"})
                except Exception as e:
                    logger.debug(f"XPath extraction for new_email_link failed: {e}")

            device.tap(response.new_email_link, "new email link (AgentQL)")
            time.sleep(random.uniform(*DELAYS["after_click"]))
            is_split_mode = True
            # Re-query after clicking
            response = agentql_page.query_elements(EMAIL_STEP_QUERY)
        except Exception:
            pass

    # Even if we didn't click the link, detect split mode via dropdown
    if not is_split_mode:
        is_split_mode = _is_split_mode(page)

    if not response.email_input:
        logger.warning("AgentQL could not find email input")
        return False

    # Extract and cache XPaths for future use
    if DOMPATH_AVAILABLE:
        try:
            if response.email_input:
                extract_and_cache_xpath(response.email_input, "email_input", {"step": "email"})
            if response.next_button:
                extract_and_cache_xpath(response.next_button, "email_next", {"step": "email"})
        except Exception as e:
            logger.warning(f"XPath extraction failed: {e}")

    # Determine what to type
    email_to_type = identity["email_handle"]
    if not is_split_mode:
        email_to_type = f"{identity['email_handle']}@outlook.com"

    logger.info(f"Typing email (AgentQL): {email_to_type} (split mode: {is_split_mode})")

    # Clear and type
    response.email_input.fill("")
    time.sleep(0.2)
    device.type_text(response.email_input, email_to_type, "email input (AgentQL)")

    time.sleep(random.uniform(*DELAYS["after_input"]))

    # Click next
    if response.next_button:
        device.tap(response.next_button, "next button (AgentQL)")
        time.sleep(random.uniform(*DELAYS["step_transition"]))
        return True

    return False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _check_and_handle_username_taken(page, identity: dict, device) -> bool:
    """
    Check if username is taken and add a random suffix to try again.
    Returns False to trigger a retry with the new username.
    """
    # Check for error message indicating username is taken
    try:
        page_content = page.content().lower()
        has_error = "already taken" in page_content or "try another" in page_content or "isn't available" in page_content

        if not has_error:
            # Also try error element
            error_el = page.locator(SELECTORS["email"]["error_message"]).first
            has_error = error_el.is_visible(timeout=500)
    except Exception:
        has_error = False

    if not has_error:
        return False

    logger.warning("⚠️ Username is taken! Adding suffix and retrying...")

    # Simple approach: Add a random suffix to the username
    new_suffix = str(random.randint(100, 9999))
    old_handle = identity['email_handle']

    # Get base handle (remove existing numbers at the end)
    base_handle = old_handle.rstrip('0123456789')
    if not base_handle:
        base_handle = old_handle

    identity['email_handle'] = f"{base_handle}{new_suffix}"
    logger.info(f"🔄 Rotated identity: {old_handle} -> {identity['email_handle']}")

    # Clear the input field for the retry
    try:
        email_input = page.locator(SELECTORS["email"]["input"]).first
        if email_input.is_visible(timeout=1000):
            email_input.fill("")
    except Exception:
        pass

    return False  # Return False to trigger retry loop with new username
