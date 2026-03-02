"""
Amazon Identity Verification (IDV) Flow

Handles government ID upload after developer registration and 2FA setup.
Visits: https://developer.amazon.com/settings/console/idv/landing_page

Architecture mirrors developer_registration.py and two_step_verification.py:
  - detect_idv_state(page) -> str          : URL/DOM state detection
  - run_identity_verification(...)  -> bool : State-machine orchestration

Click waterfall  (per InteractionEngine):  Cache → Selectors → AgentQL
Execution waterfall                      :  JS composite → dispatch → force
File upload                              :  expect_file_chooser → input[type=file]
"""

import os
import glob
import time
import hashlib
from pathlib import Path
from loguru import logger

from amazon.core.session import SessionState
from amazon.core.interaction import InteractionEngine
from amazon.utils.xpath_cache import get_cached_xpath, extract_and_cache_xpath

# ─── URLs ────────────────────────────────────────────────────────────────────
IDV_URL       = "https://developer.amazon.com/settings/console/idv/landing_page"
DL_OUTPUT_DIR = Path("/Users/elias/Documents/GitHub/amazon/outputs/dl")

# ─── Selectors (stable Ember data-action attributes + IDs) ──────────────────
# Ember data-action hooks are far more stable than absolute XPaths on the
# amazon.com/idverify/* pages.  The IDs (a-autoid-N) are dynamic per session
# so we treat them as last-resort fallbacks.

# Landing page — still on developer.amazon.com
SEL_VERIFY_BTN = [
    '//*[@id="Ivv_verify_btn"]/button',      # original user-supplied XPath
    '#Ivv_verify_btn button',
    'button:has-text("Verify identity")',
    'button:has-text("Verify")',
]

# Document selection — amazon.com/idverify/document/country-and-document-type
# Defaults are already Australia / Driver Licence so we just click Continue.
# Amazon's a-button-input has opacity:.01 — is_visible() returns False.
# Use count() > 0 + JS click instead.
SEL_DOC_CONTINUE = [
    '//*[@id="a-autoid-2"]/span/input',                          # user-supplied XPath (most reliable)
    'span.ivv-document-metadata-form__submit-button input',
    '#a-autoid-2 input',
    'input.a-button-input[type="submit"]',
    'input[type="submit"]',
    'button:has-text("Continue")',
]
# Dropdown selectors kept for fallback verification only
SEL_COUNTRY_DROPDOWN = ['#a-autoid-0-announce', '#a-autoid-0', '[data-action="a-dropdown-select"]']
SEL_AUSTRALIA_OPT    = ['#country_10', 'li:has-text("Australia")', 'a:has-text("Australia")']
SEL_TYPE_DROPDOWN    = ['#a-autoid-1-announce', '#a-autoid-1']
SEL_DRIVER_LICENCE   = ['#documentType_1', 'li:has-text("Driver")', 'a:has-text("Licence")']

# Upload pages — amazon.com/idverify/document/front-and-back-image-mobile
# Ember action hooks on the "Upload ID instead" links
SEL_FRONT_UPLOAD_LINK = [
    '[data-action="ivv-choose-document-front-image-from-device"] a',
    '[data-ivv-choose-document-front-image-from-device] a',
    'a.ivv-link:has-text("Upload ID instead")',
    'a:has-text("Upload ID instead")',
]
SEL_BACK_UPLOAD_LINK = [
    '[data-action="ivv-choose-document-back-image-from-device"] a',
    '[data-ivv-choose-document-back-image-from-device] a',
    'a.ivv-link:has-text("Upload ID instead")',
    'a:has-text("Upload ID instead")',
]

# File inputs revealed after clicking the upload link
# NOTE: Both front and back inputs live on the SAME page (front-and-back-image-mobile).
# The generic 'input[type="file"]' fallback is intentionally omitted from SEL_BACK_FILE_INPUT
# to avoid accidentally setting the front input when both are present in the DOM.
SEL_FRONT_FILE_INPUT = [
    '[data-action="ivv-document-front-image-input-file"] input[type="file"]',
    '[data-ivv-document-front-image-input-file] input[type="file"]',
    '.ivv-document-front-image-input-file input[type="file"]',
    'input[type="file"]:first-of-type',          # safe only on front-only page
]
SEL_BACK_FILE_INPUT = [
    '[data-action="ivv-document-back-image-input-file"] input[type="file"]',
    '[data-ivv-document-back-image-input-file] input[type="file"]',
    '.ivv-document-back-image-input-file input[type="file"]',
    # positional fallback — back input is always the second one on this page
    'input[type="file"]:nth-of-type(2)',
    '(//input[@type="file"])[2]',
]

# Continue after front/back image confirmation
SEL_FRONT_CONFIRM_CONTINUE = [
    '[data-ivv-component="document-front-image-confirmation"] button',
    '[data-ivv-component="document-front-image-confirmation"] input[type="submit"]',
    'button:has-text("Continue")',
    'input.a-button-input[type="submit"]',
]
SEL_BACK_CONFIRM_CONTINUE = [
    '[data-ivv-component="document-back-image-confirmation"] button',
    '[data-ivv-component="document-back-image-confirmation"] input[type="submit"]',
    'button:has-text("Continue")',
    'input.a-button-input[type="submit"]',
]

# Try Again button — shown on the "we couldn't verify" failure page
SEL_TRY_AGAIN = [
    'button:has-text("Try again")',
    'button:has-text("Try Again")',
    'a:has-text("Try again")',
    'a:has-text("Try Again")',
    '[data-action="ivv-try-again"] button',
    '[data-action="ivv-try-again"] a',
    'input.a-button-input[value*="Try"]',
]

# ─── AgentQL fallback queries (used only when CSS selectors fail) ─────────────
IDV_AQL = {
    "landing_page":       '{ verify_identity_button }',
    "document_selection": '{ continue_button }',
    "upload_front":       '{ upload_id_instead_link }',
    "confirm_front":      '{ continue_button }',
    "upload_back":        '{ upload_id_instead_link }',
    "confirm_back":       '{ continue_button }',
}


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _safe_is_visible(locator, timeout: int = 500) -> bool:
    """Safe visibility check — never raises Patchright 'n-th element' errors."""
    try:
        return locator.is_visible(timeout=timeout)
    except Exception:
        return False


def _wait_for_page_stable(page, timeout: int = 8000):
    """Wait for the page to stop loading (networkidle) with a safe fallback."""
    try:
        page.wait_for_load_state("networkidle", timeout=timeout)
    except Exception:
        try:
            page.wait_for_load_state("domcontentloaded", timeout=3000)
        except Exception:
            time.sleep(1.5)


def _click_verify_btn(page) -> bool:
    """
    Dedicated handler for the 'Verify Identity' button on
    developer.amazon.com/settings/console/idv/landing_page.

    Does NOT rely on is_visible() — it scrolls each candidate into view
    and fires a JS composite click directly on the DOM element.
    """
    _wait_for_page_stable(page)

    # Candidate selectors (ordered: user-supplied XPath first)
    candidates = [
        '//*[@id="Ivv_verify_btn"]/button',
        '#Ivv_verify_btn button',
        '#Ivv_verify_btn input',
        'button:has-text("Verify Identity")',
        'button:has-text("Verify identity")',
        '[data-test-id="ivv-verify-btn"]',
        'a:has-text("Verify Identity")',
    ]

    for sel in candidates:
        try:
            loc = page.locator(sel).first
            # count() = 0 means no match at all → skip early
            if loc.count() == 0:
                continue
            loc.scroll_into_view_if_needed(timeout=3000)
            time.sleep(0.3)
            if _js_composite_click(page, loc, f"Verify Identity ({sel[:40]})"):
                logger.success(f"✅ Clicked Verify Identity via: {sel[:60]}")
                return True
        except Exception as e:
            logger.debug(f"Selector failed '{sel[:50]}': {e}")
            continue

    # Last resort: AgentQL semantic query
    logger.info("Falling back to AgentQL for Verify Identity button…")
    try:
        import agentql
        aql = agentql.wrap(page) if not hasattr(page, 'query_elements') else page
        resp = aql.query_elements('{ verify_identity_button }')
        btn  = getattr(resp, 'verify_identity_button', None)
        if btn:
            btn.scroll_into_view_if_needed(timeout=3000)
            time.sleep(0.3)
            if _js_composite_click(page, btn, "Verify Identity (AgentQL)"):
                logger.success("✅ Clicked Verify Identity via AgentQL")
                return True
    except Exception as e:
        logger.warning(f"AgentQL Verify Identity fallback failed: {e}")

    return False



def _js_composite_click(page, element, description: str) -> bool:
    """
    JS composite click waterfall exactly matching the pattern used in
    two_step_verification.py and developer_registration.py.

    Order:
      1. Direct .click() via JS
      2. MouseEvent dispatch (bubbles=True → handles React synthetic events)
      3. Playwright force-click as final fallback
    """
    try:
        element.evaluate("el => el.click()")
        element.evaluate("""el => {
            ['mousedown', 'click', 'mouseup'].forEach(name => {
                el.dispatchEvent(new MouseEvent(name, {
                    bubbles: true, cancelable: true,
                    view: window, buttons: 1
                }));
            });
        }""")
        try:
            element.click(force=True, timeout=1500)
        except Exception:
            pass
        logger.info(f"⚡ JS Composite click → '{description}'")
        return True
    except Exception as e:
        logger.warning(f"JS composite click failed for '{description}': {e}")
        return False


# ─────────────────────────────────────────────────────────────────────────────
# State detection
# ─────────────────────────────────────────────────────────────────────────────

def detect_idv_state(page) -> str:
    """
    Detect the current step in the Amazon IDV flow.

    The flow spans TWO domains:
      developer.amazon.com  → landing_page
      amazon.com/idverify/* → document_selection, upload_front, confirm_front,
                              upload_back, confirm_back, processing, success

    Priority (most-specific first to avoid false positives):
      success → processing → confirm_back → confirm_front
              → upload_back → upload_front → document_selection → landing_page → unknown
    """
    if page.is_closed():
        return "unknown"

    url = page.url.lower()

    # 1. SUCCESS ─────────────────────────────────────────────────────────────
    # Primary: exact banner text shown on the developer console after IDV completes
    if _safe_is_visible(page.get_by_text("Identity Verified Successfully", exact=False), timeout=400):
        return "success"
    # Also treat the developer console settings page post-verification as success
    # (URL lands there after the green banner is acknowledged)
    if "developer.amazon.com" in url and "idv" not in url and \
       _safe_is_visible(page.get_by_text("You can now continue to upload and test your apps", exact=False), timeout=300):
        return "success"

    success_texts = [
        "document has been submitted",
        "identity verification submitted",
        "thank you for submitting",
        "your documents have been received",
        "under review",
        "pending review",
        "verification complete",
        "identity verified",
        "we have received your documents",
        "submitted for review",
    ]
    for txt in success_texts:
        if _safe_is_visible(page.get_by_text(txt, exact=False), timeout=300):
            return "success"

    # 2. IDV FAILED — "We couldn't verify your ID" page with a Try Again button
    # URL: amazon.com/idverify/document/status (same path as processing but with error UI)
    idv_failed_texts = [
        "we couldn't verify your id",
        "we could not verify your id",
        "couldn't verify your id",
        "we're having trouble verifying your identity",
        "we are having trouble verifying your identity",
        "having trouble verifying",
        "we couldn't verify your identity",
        "we could not verify your identity",
        "couldn't verify your identity",
        "could not verify your identity",
    ]
    for txt in idv_failed_texts:
        if _safe_is_visible(page.get_by_text(txt, exact=False), timeout=300):
            return "idv_failed"
    # URL-based detection: status page + Try Again button visible = failed (not processing)
    if "idverify/document/status" in url:
        for sel in ['button:has-text("Try again")', 'button:has-text("Try Again")', 'a:has-text("Try again")']:
            try:
                if page.locator(sel).count() > 0:
                    return "idv_failed"
            except Exception:
                pass

    # 3. REJECTED ────────────────────────────────────────────────────────────
    # amazon.com/idverify/document/status with a hard failure message
    # (no retry offered — Amazon will not accept this document)
    rejection_texts = [
        "name on your id doesn't match",
        "name on your id does not match",
        "use another id",
        "id could not be verified",
        "unable to verify your identity",
        "document could not be read",
        "document was not accepted",
        "image was not accepted",
        "try again with a different id",
        "id type is not supported",
    ]
    for txt in rejection_texts:
        if _safe_is_visible(page.get_by_text(txt, exact=False), timeout=300):
            return "rejected"

    # 3. PROCESSING ──────────────────────────────────────────────────────────
    # amazon.com/idverify/document/status  — "We're verifying your identity"
    if "idverify/document/status" in url or \
       _safe_is_visible(page.get_by_text("We're verifying your identity", exact=False), timeout=400) or \
       _safe_is_visible(page.get_by_text("verifying your identity", exact=False), timeout=400):
        return "processing"

    # ── All remaining states are on the front-and-back-image page ────────────
    # amazon.com/idverify/document/front-and-back-image-mobile
    on_upload_page = "front-and-back-image" in url

    if on_upload_page or "idverify" in url:
        # ── Check upload states FIRST (before confirm) ───────────────────────
        # "Upload ID instead" link is ONLY present when the camera/capture UI is
        # showing — it disappears once an image has been accepted.  This is the
        # most reliable single signal for upload_back vs confirm_back.

        # 3. UPLOAD BACK — back camera/upload section is visible
        #    Key signal: the back-side "Upload ID instead" anchor is present,
        #    OR the "Back of driver license" heading is visible.
        #    "back of your" (from "Place the back of your…") is also unique here.
        #    Do NOT use this text in confirm_back — it's from the camera page.
        back_upload_link_visible = (
            _safe_is_visible(page.locator('[data-action="ivv-choose-document-back-image-from-device"] a').first, timeout=600) or
            _safe_is_visible(page.locator('a:has-text("Upload ID instead")').last, timeout=600)
        )
        has_back_upload = (
            back_upload_link_visible or
            _safe_is_visible(page.get_by_text("Back of driver license", exact=False), timeout=400) or
            _safe_is_visible(page.get_by_text("Place the back of your", exact=False), timeout=400)
        )
        if has_back_upload:
            return "upload_back"

        # 4. UPLOAD FRONT — front camera/upload section is visible
        front_upload_link_visible = (
            _safe_is_visible(page.locator('[data-action="ivv-choose-document-front-image-from-device"] a').first, timeout=600)
        )
        has_front_upload = (
            front_upload_link_visible or
            _safe_is_visible(page.get_by_text("Front of driver license", exact=False), timeout=400) or
            _safe_is_visible(page.get_by_text("Place the front of your", exact=False), timeout=400)
        )
        if has_front_upload:
            return "upload_front"

        # 5. CONFIRM BACK — back image preview is showing, "Upload ID instead" is gone
        #    Use ONLY specific confirmation signals — never generic "Back of your"
        #    which also appears on the camera page.
        has_back_confirm = (
            _safe_is_visible(page.locator('[data-ivv-component="document-back-image-confirmation"]').first, timeout=600) or
            _safe_is_visible(page.get_by_text("Confirm back of", exact=False), timeout=400) or
            _safe_is_visible(page.get_by_text("Retake back", exact=False), timeout=400)
        )
        if has_back_confirm:
            return "confirm_back"

        # 6. CONFIRM FRONT — front image preview is showing, back not yet uploaded
        has_front_confirm = (
            _safe_is_visible(page.locator('[data-ivv-component="document-front-image-confirmation"]').first, timeout=600) or
            _safe_is_visible(page.get_by_text("Confirm front of", exact=False), timeout=400) or
            _safe_is_visible(page.get_by_text("Retake front", exact=False), timeout=400)
        )
        if has_front_confirm:
            return "confirm_front"

    # 7. LANDING PAGE ────────────────────────────────────────────────────────
    # developer.amazon.com/settings/console/idv/landing_page — MUST be checked
    # BEFORE document_selection because the landing page SPA can render dropdown
    # labels ("Country that issued the ID", "Type of ID") in the DOM before the
    # user clicks "Verify Identity", which would otherwise trigger the text-based
    # document_selection detector below and skip the verify button entirely.
    if "idv/landing_page" in url:
        return "landing_page"

    # Verify Identity button present → still on the landing page regardless of URL
    try:
        if _safe_is_visible(page.locator('#Ivv_verify_btn button').first, timeout=800):
            return "landing_page"
        if _safe_is_visible(page.locator('button:has-text("Verify Identity")').first, timeout=800):
            return "landing_page"
        if _safe_is_visible(page.locator('button:has-text("Verify identity")').first, timeout=800):
            return "landing_page"
    except Exception:
        pass

    # 8. CONSOLE IDV FAILED — developer.amazon.com/settings/console/home shows
    #    a red "Account Identity Verification Failed." banner BEFORE we detect
    #    this page as a generic landing_page and loop forever.
    #    Must be checked before the blanket developer.amazon.com → landing_page rule.
    if "developer.amazon.com" in url and "idverify" not in url:
        if _safe_is_visible(page.get_by_text("Account Identity Verification Failed", exact=False), timeout=600) or \
           _safe_is_visible(page.get_by_text("identity verification has failed", exact=False), timeout=600):
            return "console_failed"
        return "landing_page"

    # 9. DOCUMENT SELECTION ──────────────────────────────────────────────────
    # amazon.com/idverify/document/country-and-document-type
    if "country-and-document-type" in url or \
       _safe_is_visible(page.get_by_text("Country that issued the ID", exact=False), timeout=500) or \
       _safe_is_visible(page.get_by_text("Select your ID type", exact=False), timeout=500) or \
       _safe_is_visible(page.get_by_text("Type of ID", exact=False), timeout=500):
        return "document_selection"

    return "unknown"


# ─────────────────────────────────────────────────────────────────────────────
# DL image helpers
# ─────────────────────────────────────────────────────────────────────────────

# Country name → DLFactory country code mapping (matches dl_templates.json keys)
_COUNTRY_TO_DL_CODE = {
    "australia":       "AU",
    "united kingdom":  "GB",
    "uk":              "GB",
    "germany":         "DE",
    "iceland":         "IS",
    "italy":           "IT",
}

# Abbreviation lookup so the DL file-name suffix matches the factory output
_COUNTRY_TO_CODE = {
    "australia":      "AU",
    "united kingdom": "GB",
    "uk":             "GB",
    "germany":        "DE",
    "iceland":        "IS",
    "italy":          "IT",
}


def _country_code_for(identity) -> str:
    """Derive DLFactory country code from the session identity's country field."""
    raw = ""
    if hasattr(identity, "country"):
        raw = (identity.country or "").lower()
    elif isinstance(identity, dict):
        raw = (identity.get("country", "") or "").lower()
    return _COUNTRY_TO_DL_CODE.get(raw, "AU")


def _deterministic_dob(identity) -> tuple:
    """
    Derive a stable date-of-birth from the identity so the same person always
    gets the same DOB on their DL.  Falls back to explicit fields if present.

    Uses sha256(firstname+lastname) → age between 25-55.
    Returns (day_str, month_str, year_str) all zero-padded.
    """
    # Explicit fields take priority (some identity generators store them)
    for src in (identity,):
        dob_day   = getattr(src, "dob_day",   None) or (src.get("dob_day")   if isinstance(src, dict) else None)
        dob_month = getattr(src, "dob_month", None) or (src.get("dob_month") if isinstance(src, dict) else None)
        dob_year  = getattr(src, "dob_year",  None) or (src.get("dob_year")  if isinstance(src, dict) else None)
        if dob_day and dob_month and dob_year:
            return str(dob_day).zfill(2), str(dob_month).zfill(2), str(dob_year)

    # Deterministic fallback: hash of name
    first = (getattr(identity, "firstname", "") or identity.get("first_name", "") if isinstance(identity, dict) else getattr(identity, "firstname", "")).lower()
    last  = (getattr(identity, "lastname",  "") or identity.get("last_name",  "") if isinstance(identity, dict) else getattr(identity, "lastname",  "")).lower()
    seed  = int(hashlib.sha256(f"{first}{last}".encode()).hexdigest(), 16)

    year  = 1970 + (seed % 30)          # 1970 – 1999  (25-55 years old in 2025)
    month = 1   + (seed >> 4  & 0xFF) % 12
    day   = 1   + (seed >> 12 & 0xFF) % 28  # safe for all months

    return f"{day:02d}", f"{month:02d}", str(year)


def _build_dl_identity(identity) -> dict:
    """
    Convert SessionState Identity (dataclass) → DLFactory identity dict.

    All fields are pulled from the live session identity so the generated DL
    matches the person used during signup/registration exactly.
    """
    # ── read primitives (works for both dataclass and plain dict) ────────────
    def _get(attr, dict_key=None, default=""):
        if hasattr(identity, attr):
            return getattr(identity, attr, default) or default
        if isinstance(identity, dict):
            return identity.get(dict_key or attr, default) or default
        return default

    first    = _get("firstname",    "first_name")
    last     = _get("lastname",     "last_name")
    address  = _get("address_line1","address")
    city     = _get("city")
    state    = _get("state")
    zip_code = _get("zip_code",     "zip")
    country  = _country_code_for(identity)

    dob_day, dob_month, dob_year = _deterministic_dob(identity)

    # city_state_zip format: "Melbourne VIC 3000"
    city_state_zip = f"{city} {state} {zip_code}".strip()

    dl_identity = {
        "first_name":     first.upper(),
        "last_name":      last.upper(),
        "country":        country,
        "address":        address.upper() if address else "77 SAMPLE ST",
        "city_state_zip": city_state_zip.upper() if city_state_zip.strip() else "MELBOURNE VIC 3000",
        "dob_day":        dob_day,
        "dob_month":      dob_month,
        "dob_year":       dob_year,
    }

    logger.info(
        f"🪪 DL identity: {dl_identity['first_name']} {dl_identity['last_name']} | "
        f"DOB {dob_day}/{dob_month}/{dob_year} | Country {country}"
    )
    return dl_identity


def _find_existing_dl(identity) -> tuple:
    """
    Look for pre-generated DL images in outputs/dl/ that match this identity.
    Checks exact name+country filename first, then falls back to any matching country.
    Returns (front_path, back_path) — either or both may be None.
    """
    DL_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    last_name = (
        getattr(identity, "lastname", "") or
        (identity.get("last_name", "") if isinstance(identity, dict) else "")
    ).upper()
    country = _country_code_for(identity)

    # Exact match: DL_SMITH_AU.png / DL_SMITH_AU_BACK.png
    front_exact = DL_OUTPUT_DIR / f"DL_{last_name}_{country}.png"
    back_exact  = DL_OUTPUT_DIR / f"DL_{last_name}_{country}_BACK.png"

    front_path = str(front_exact) if front_exact.exists() else None
    back_path  = str(back_exact)  if back_exact.exists()  else None

    # Fuzzy fallback: newest DL for this country
    if not front_path:
        candidates = sorted(glob.glob(str(DL_OUTPUT_DIR / f"DL_*_{country}.png")))
        if candidates:
            front_path = candidates[-1]
            logger.info(f"Using existing DL front: {Path(front_path).name}")

    if not back_path:
        candidates = sorted(glob.glob(str(DL_OUTPUT_DIR / f"DL_*_{country}_BACK.png")))
        if candidates:
            back_path = candidates[-1]
            logger.info(f"Using existing DL back: {Path(back_path).name}")

    return front_path, back_path


def _generate_dl(identity) -> tuple:
    """
    Generate a Driver's Licence via DLFactory using the session identity.
    Returns (front_path, back_path) — either may be None on failure.
    """
    dl_identity = _build_dl_identity(identity)
    country     = dl_identity["country"]
    logger.info(f"🏭 Generating {country} Driver's Licence for {dl_identity['first_name']} {dl_identity['last_name']}…")
    try:
        from amazon.modules.dl_factory import DLFactory
        factory    = DLFactory()
        front_path = factory.create_license(dl_identity)
        back_path  = factory.create_license_back(dl_identity)
        if front_path:
            logger.success(f"✅ DL front generated: {Path(front_path).name}")
        if back_path:
            logger.success(f"✅ DL back  generated: {Path(back_path).name}")
        return front_path, back_path
    except Exception as e:
        logger.error(f"DLFactory generation failed: {e}")
        return None, None


def _resolve_dl_images(identity) -> tuple:
    """
    Always generate a fresh DL set from the current session identity so the
    name/DOB on the document exactly matches what Amazon registered for this
    account.  Reusing stale images risks a name-mismatch rejection.
    """
    logger.info("🏭 Generating fresh DL images from session identity…")
    front, back = _generate_dl(identity)

    # Fallback: if generation fails, try existing files as last resort
    if not front or not back:
        logger.warning("DL generation failed — falling back to existing images")
        front, back = _find_existing_dl(identity)

    return front, back


# ─────────────────────────────────────────────────────────────────────────────
# Upload helper
# ─────────────────────────────────────────────────────────────────────────────

def _reveal_and_set_file_input(page, selectors: list, file_path: str, step_name: str) -> bool:
    """
    Reveal ALL file inputs via JS (removes hidden/opacity:0 CSS) then call
    set_input_files on the first matching selector.

    This completely bypasses the 'Upload ID instead' link click and the
    resulting OS native file-picker dialog — no dialog ever opens.
    """
    # Reveal every file input on the page so Playwright can interact with them
    try:
        page.evaluate("""
            () => {
                document.querySelectorAll('input[type="file"]').forEach(inp => {
                    inp.style.display    = 'block';
                    inp.style.visibility = 'visible';
                    inp.style.opacity    = '1';
                    inp.style.position   = 'static';
                    inp.removeAttribute('tabindex');
                });
            }
        """)
    except Exception as e:
        logger.warning(f"JS reveal failed for {step_name}: {e}")

    for sel in selectors:
        try:
            prefix = "xpath=" if sel.startswith("/") or sel.startswith("(") else ""
            loc = page.locator(f"{prefix}{sel}").first
            if loc.count() == 0:
                continue
            loc.set_input_files(file_path)
            logger.success(f"✅ File injected via '{sel[:60]}' — {step_name}")
            return True
        except Exception as e:
            logger.debug(f"set_input_files failed '{sel[:50]}': {e}")
            continue
    return False


def _upload_side(
    page,
    upload_link_selectors: list,
    file_input_selectors: list,
    file_path: str,
    step_name: str,
    interaction: InteractionEngine,
) -> bool:
    """
    Upload one document side (front or back) without triggering any OS dialog.

    Strategy A — JS-reveal + set_input_files directly on hidden input.
                 No link click → no file-picker dialog opens at all.
    Strategy B — Playwright expect_file_chooser interceptor (catches the
                 chooser event before the OS dialog renders, then closes it
                 by fulfilling it programmatically).
    """
    logger.info(f"📤 Uploading {step_name}: {Path(file_path).name}")

    # ── Strategy A: direct JS inject — never opens OS dialog ────────────────
    uploaded = _reveal_and_set_file_input(page, file_input_selectors, file_path, step_name)

    # ── Strategy B: expect_file_chooser interception ─────────────────────────
    # Playwright intercepts the chooser event and fulfils it before the OS
    # picker is rendered — the dialog never becomes visible to the user.
    if not uploaded:
        logger.info(f"Direct inject failed, trying file-chooser intercept — {step_name}")
        try:
            with page.expect_file_chooser(timeout=8000) as fc_info:
                # Click "Upload ID instead" only inside the chooser context so
                # Playwright can intercept the chooser event immediately
                for sel in upload_link_selectors:
                    try:
                        el = page.locator(sel).first
                        if el.count() > 0:
                            _js_composite_click(page, el, f"Upload instead ({step_name})")
                            break
                    except Exception:
                        continue
            fc_info.value.set_files(file_path)
            logger.success(f"✅ File-chooser intercept OK — {step_name}")
            uploaded = True
        except Exception as e:
            logger.warning(f"File-chooser intercept failed ({e})")

    if not uploaded:
        logger.error(f"❌ All upload methods failed for {step_name}")
        return False

    time.sleep(1.5)
    return True


def _click_continue(page, selectors: list, step_name: str, interaction: InteractionEngine) -> bool:
    """
    Click a Continue / Submit button.

    Amazon's buttons use a-button-input which has opacity:.01 and
    position:absolute — Playwright's is_visible() returns False even though
    the element exists and is fully clickable.  We gate on count() > 0 instead
    and fire a JS composite click directly on the DOM node.
    """
    for sel in selectors:
        try:
            prefix = "xpath=" if sel.startswith("/") or sel.startswith("(") else ""
            loc = page.locator(f"{prefix}{sel}").first
            if loc.count() == 0:
                continue
            # Scroll into view in case it's below the fold
            try:
                loc.scroll_into_view_if_needed(timeout=2000)
            except Exception:
                pass
            if _js_composite_click(page, loc, f"Continue ({step_name}) via {sel[:50]}"):
                logger.info(f"✅ Clicked Continue — {step_name}")
                time.sleep(2)
                return True
        except Exception as e:
            logger.debug(f"_click_continue selector failed '{sel[:50]}': {e}")
            continue

    # Last resort: AgentQL
    logger.warning(f"Continue button not found via selectors for {step_name}, trying AgentQL…")
    ok = interaction.smart_click(
        f"Continue ({step_name})",
        selectors=selectors,
        agentql_query="{ continue_button }",
        cache_key=f"idv_{step_name}_continue",
        biomechanical=True,
    )
    if ok:
        time.sleep(2)
    return ok


# ─────────────────────────────────────────────────────────────────────────────
# Main state-machine
# ─────────────────────────────────────────────────────────────────────────────

def run_identity_verification(playwright_page, session: SessionState, device) -> bool:
    """
    State-machine driven Identity Verification flow.

    Flow (two domains):
      developer.amazon.com
        landing_page       → click 'Verify Identity' → redirects to amazon.com/idverify/

      amazon.com/idverify/
        document_selection → verify Australia + Driver Licence defaults, click Continue
        upload_front       → click 'Upload ID instead', set front DL image
        confirm_front      → front preview shown, click Continue
        upload_back        → click 'Upload ID instead', set back DL image
        confirm_back       → back preview shown, click Continue
        processing         → Amazon verifying (wait up to 30s)
        success            → set idv_submitted flag, return True
    """
    logger.info("🪪 Starting Identity Verification Flow…")

    if not session.identity:
        logger.error("No identity in session — cannot run IDV")
        return False

    identity = session.identity

    # ── Open a fresh tab to avoid TargetClosedError from stale pages ─────────
    # (mirrors the pattern in developer_registration.py)
    try:
        logger.info("🆕 Opening fresh tab for IDV…")
        context  = playwright_page.context
        new_page = context.new_page()
        if not playwright_page.is_closed():
            try:
                playwright_page.close()
            except Exception:
                pass
        playwright_page = new_page
        device.page     = playwright_page
    except Exception as e:
        logger.warning(f"Could not open fresh tab: {e} — continuing on existing page")

    interaction = InteractionEngine(playwright_page, device)

    # ── Pre-resolve DL images (find or generate) ──────────────────────────────
    front_path, back_path = _resolve_dl_images(identity)
    if not front_path or not back_path:
        logger.error("❌ DL image(s) unavailable — aborting IDV")
        return False

    logger.info(f"📂 DL Front : {front_path}")
    logger.info(f"📂 DL Back  : {back_path}")

    # ── Navigate directly to the IDV landing page ─────────────────────────────
    logger.info(f"🌐 Navigating to IDV landing page: {IDV_URL}")
    try:
        playwright_page.goto(IDV_URL, wait_until="domcontentloaded", timeout=30000)
        _wait_for_page_stable(playwright_page)
    except Exception as e:
        logger.error(f"Initial navigation to IDV URL failed: {e}")
        return False

    # ── State-machine loop ────────────────────────────────────────────────────
    max_steps = 18
    for step in range(max_steps):

        # Guard: tab still alive
        if playwright_page.is_closed():
            logger.error("Tab closed unexpectedly inside IDV loop")
            return False

        state = detect_idv_state(playwright_page)
        logger.info(f"🪪 IDV [{step + 1}/{max_steps}] State = '{state}'")

        # ── SUCCESS ───────────────────────────────────────────────────────────
        if state == "success":
            logger.success("✅ Identity Verified Successfully — automation complete!")
            session.update_flag("idv_submitted", True)
            session.update_flag("idv_verified", True)
            session.set_status("IDV_SUCCESS")
            return True

        # ── REJECTED — Amazon rejected the document on idverify status page ──
        elif state == "rejected":
            try:
                reason = playwright_page.locator("h1, h2, h3, p").first.inner_text(timeout=2000).strip()
            except Exception:
                reason = "IDV rejected by Amazon (reason unknown)"
            logger.error(f"❌ IDV rejected: {reason}")
            session.set_metadata("idv_failure_reason", reason)
            session.set_status("IDV_REJECTED")
            return False

        # ── IDV FAILED — "We couldn't verify your identity" with Try Again button ─
        elif state == "idv_failed":
            logger.warning("⚠️  Amazon could not verify identity — attempting 'Try Again'…")
            clicked = False
            for sel in SEL_TRY_AGAIN:
                try:
                    loc = playwright_page.locator(sel).first
                    if loc.count() == 0:
                        continue
                    try:
                        loc.scroll_into_view_if_needed(timeout=2000)
                    except Exception:
                        pass
                    if _js_composite_click(playwright_page, loc, f"Try Again ({sel[:40]})"):
                        logger.success(f"✅ Clicked 'Try Again' via: {sel[:60]}")
                        clicked = True
                        break
                except Exception as e:
                    logger.debug(f"Try Again selector failed '{sel[:50]}': {e}")
                    continue
            if not clicked:
                # AgentQL semantic fallback
                logger.info("AgentQL fallback for Try Again button…")
                ok = interaction.smart_click(
                    "Try Again",
                    selectors=SEL_TRY_AGAIN,
                    agentql_query="{ try_again_button }",
                    cache_key="idv_try_again",
                    biomechanical=True,
                )
                if not ok:
                    logger.error("❌ Could not click 'Try Again' — aborting IDV")
                    session.set_status("IDV_FAILED")
                    return False
            _wait_for_page_stable(playwright_page)
            time.sleep(2)

        # ── CONSOLE FAILED — developer console banner: "Account Identity
        # Verification Failed." — Amazon has already processed and rejected us.
        elif state == "console_failed":
            try:
                # Grab the full banner text for the reason
                banner = playwright_page.locator(".a-alert-content, .a-box-inner").first.inner_text(timeout=2000).strip()
            except Exception:
                banner = "Account Identity Verification Failed (console banner)"
            logger.error(f"❌ IDV console failure detected: {banner}")
            session.set_metadata("idv_failure_reason", banner)
            session.set_status("IDV_REJECTED")
            return False

        # ── PROCESSING — wait for Amazon to finish verifying ─────────────────
        elif state == "processing":
            logger.info("⏳ Amazon is verifying the documents — waiting up to 30s…")
            for _ in range(6):   # 6 × 5s = 30s max
                time.sleep(5)
                if playwright_page.is_closed():
                    return False
                next_state = detect_idv_state(playwright_page)
                if next_state != "processing":
                    logger.info(f"Processing resolved → '{next_state}'")
                    break
            # loop will re-detect on next iteration

        # ── UNKNOWN → navigate to IDV landing ────────────────────────────────
        elif state == "unknown":
            logger.info(f"Unknown state on {playwright_page.url!r} — re-navigating to IDV landing")
            try:
                playwright_page.goto(IDV_URL, wait_until="domcontentloaded", timeout=30000)
                _wait_for_page_stable(playwright_page)
            except Exception as e:
                logger.error(f"Navigation to IDV URL failed: {e}")
            time.sleep(2)

        # ── LANDING PAGE → click Verify Identity, wait for redirect ──────────
        elif state == "landing_page":
            logger.info("🔘 PAGE: Landing — clicking 'Verify Identity'…")
            _wait_for_page_stable(playwright_page)

            ok = _click_verify_btn(playwright_page)
            if ok:
                logger.info("⏳ Waiting for redirect to amazon.com/idverify…")
                try:
                    playwright_page.wait_for_url(
                        lambda u: "amazon.com/idverify" in u or "idverify" in u,
                        timeout=20000,
                    )
                    logger.info(f"↪ Redirected to: {playwright_page.url}")
                except Exception:
                    # Timeout is non-fatal — state loop will re-detect
                    time.sleep(3)
            else:
                logger.warning("Could not click Verify Identity — will retry")
                time.sleep(3)

        # ── DOCUMENT SELECTION (amazon.com/idverify/document/country-and-document-type)
        # Page defaults: Country = Australia, Type = Driver License
        # Screenshot confirms defaults are already correct — just click Continue.
        elif state == "document_selection":
            logger.info("📋 PAGE: Document selection — verifying defaults and clicking Continue…")
            _wait_for_page_stable(playwright_page)

            # Read visible text of each dropdown; fix only if wrong
            # (use the full button-inner text, not the announce span which can be empty)
            def _dropdown_text(page, selectors) -> str:
                for sel in selectors:
                    try:
                        txt = page.locator(sel).first.inner_text(timeout=1500).strip()
                        if txt:
                            return txt.lower()
                    except Exception:
                        continue
                return ""

            COUNTRY_TEXT_SELS = [
                '.ivv-document-metadata-form .a-dropdown-container:first-child .a-button-text',
                '#a-autoid-0-announce',
                '[id^="a-autoid"] .a-button-text',
            ]
            TYPE_TEXT_SELS = [
                '.ivv-document-metadata-form .a-dropdown-container:last-child .a-button-text',
                '#a-autoid-1-announce',
            ]

            country_text = _dropdown_text(playwright_page, COUNTRY_TEXT_SELS)
            logger.info(f"Country dropdown reads: '{country_text or '(undetected)'}' — "
                        f"{'OK' if 'australia' in country_text or not country_text else 'WRONG'}")

            if country_text and "australia" not in country_text:
                logger.info("Country wrong — correcting…")
                interaction.smart_click("Country dropdown", selectors=SEL_COUNTRY_DROPDOWN,
                                        cache_key="idv_country_dropdown")
                time.sleep(0.6)
                interaction.smart_click("Australia option", selectors=SEL_AUSTRALIA_OPT,
                                        cache_key="idv_australia_option")
                time.sleep(0.8)

            type_text = _dropdown_text(playwright_page, TYPE_TEXT_SELS)
            logger.info(f"Type dropdown reads: '{type_text or '(undetected)'}' — "
                        f"{'OK' if any(k in type_text for k in ('driver','licence','license')) or not type_text else 'WRONG'}")

            if type_text and not any(k in type_text for k in ("driver", "licence", "license")):
                logger.info("Document type wrong — correcting…")
                interaction.smart_click("Type dropdown", selectors=SEL_TYPE_DROPDOWN,
                                        cache_key="idv_type_dropdown")
                time.sleep(0.6)
                interaction.smart_click("Driver Licence option", selectors=SEL_DRIVER_LICENCE,
                                        cache_key="idv_driver_licence_option")
                time.sleep(0.8)

            # ── Click Continue ────────────────────────────────────────────────
            ok = _click_continue(playwright_page, SEL_DOC_CONTINUE, "document_selection", interaction)
            if ok:
                logger.info("⏳ Waiting for upload page…")
                try:
                    playwright_page.wait_for_url(
                        lambda u: "front-and-back" in u or "idverify" in u,
                        timeout=15000,
                    )
                    logger.info(f"↪ Moved to: {playwright_page.url}")
                except Exception:
                    time.sleep(2)
            else:
                logger.error("Continue failed on document selection — retrying")
                time.sleep(2)

        # ── UPLOAD FRONT ──────────────────────────────────────────────────────
        elif state == "upload_front":
            logger.info("📄 Uploading front of Driver's Licence…")
            ok = _upload_side(
                playwright_page,
                upload_link_selectors = SEL_FRONT_UPLOAD_LINK,
                file_input_selectors  = SEL_FRONT_FILE_INPUT,
                file_path             = front_path,
                step_name             = "front",
                interaction           = interaction,
            )
            if not ok:
                logger.error("Front upload failed — will retry")
                time.sleep(3)
            # After upload, the page shows a confirmation — state loop will
            # re-detect as confirm_front on next iteration

        # ── CONFIRM FRONT — image preview shown, click Continue ───────────────
        elif state == "confirm_front":
            logger.info("✅ Front image confirmed — clicking Continue…")
            _click_continue(playwright_page, SEL_FRONT_CONFIRM_CONTINUE, "confirm_front", interaction)

        # ── UPLOAD BACK ───────────────────────────────────────────────────────
        elif state == "upload_back":
            logger.info("📄 Uploading back of Driver's Licence…")
            ok = _upload_side(
                playwright_page,
                upload_link_selectors = SEL_BACK_UPLOAD_LINK,
                file_input_selectors  = SEL_BACK_FILE_INPUT,
                file_path             = back_path,
                step_name             = "back",
                interaction           = interaction,
            )
            if not ok:
                logger.error("Back upload failed — will retry")
                time.sleep(3)

        # ── CONFIRM BACK — image preview shown, click Continue ────────────────
        elif state == "confirm_back":
            logger.info("✅ Back image confirmed — clicking Continue…")
            _click_continue(playwright_page, SEL_BACK_CONFIRM_CONTINUE, "confirm_back", interaction)

    logger.error(f"❌ IDV flow exhausted {max_steps} steps without reaching 'success'")
    return False
