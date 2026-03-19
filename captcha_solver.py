"""
Amazon CAPTCHA Solver — Hybrid (AI Vision → Capsolver → Manual)

Handles:
  - Amazon CVF grid puzzles ("Choose all the [object]")
  - Amazon text CAPTCHAs ("Type the characters")
  - reCAPTCHA v2 image grids (fallback)

Tiered approach:
  1. AI Vision (OpenAI GPT-4o > Gemini > OpenRouter > Grok)
  2. Capsolver API (AwsWafClassification / ReCaptchaV2Classification)
  3. Manual Intervention (configurable)
"""

import os
import re
import time
import base64
import random
import json
import requests
from loguru import logger
from dotenv import load_dotenv
from typing import Dict, List, Optional, Any

load_dotenv()

# ── Optional SDK imports ────────────────────────────────────────────
try:
    import openai
except ImportError:
    openai = None

try:
    import capsolver
except ImportError:
    capsolver = None

try:
    from PIL import Image
except ImportError:
    Image = None

import requests
from io import BytesIO


# ── Capsolver question mappings (ReCaptchaV2Classification) ─────────
RECAPTCHA_QUESTION_IDS = {
    "taxi":           "/m/0pg52",
    "taxis":          "/m/0pg52",
    "bus":            "/m/01bjv",
    "school bus":     "/m/02yvhj",
    "motorcycle":     "/m/04_sv",
    "motorcycles":    "/m/04_sv",
    "tractor":        "/m/013xlm",
    "tractors":       "/m/013xlm",
    "chimney":        "/m/01jk_4",
    "chimneys":       "/m/01jk_4",
    "crosswalk":      "/m/014xcs",
    "crosswalks":     "/m/014xcs",
    "traffic light":  "/m/015qff",
    "traffic lights": "/m/015qff",
    "bicycle":        "/m/0199g",
    "bicycles":       "/m/0199g",
    "parking meter":  "/m/015qbp",
    "parking meters": "/m/015qbp",
    "car":            "/m/0k4j",
    "cars":           "/m/0k4j",
    "bridge":         "/m/015kr",
    "bridges":        "/m/015kr",
    "boat":           "/m/019jd",
    "boats":          "/m/019jd",
    "palm tree":      "/m/0cdl1",
    "palm trees":     "/m/0cdl1",
    "mountain":       "/m/09d_r",
    "mountains":      "/m/09d_r",
    "fire hydrant":   "/m/01pns0",
    "fire hydrants":  "/m/01pns0",
    "stair":          "/m/01lynh",
    "stairs":         "/m/01lynh",
}

# Amazon CVF uses "aws:grid:<object>" format
AWS_WAF_QUESTION_FMT = "aws:grid:{obj}"

# Capsolver only supports these specific objects (SINGULAR form)
# Source: https://docs.capsolver.com/en/guide/recognition/AwsWafClassification.html
AWS_WAF_SUPPORTED_OBJECTS = {
    # singular → capsolver question value
    "bed": "bed", "beds": "bed",
    "bag": "bag", "bags": "bag",
    "hat": "hat", "hats": "hat",
    "chair": "chair", "chairs": "chair",
    "bucket": "bucket", "buckets": "bucket",
    "curtain": "curtain", "curtains": "curtain",
    "mop": "mop", "mops": "mop",
    "clock": "clock", "clocks": "clock",
    "suitcase": "suitcase", "suitcases": "suitcase",
    "binocular": "binocular", "binoculars": "binocular",
    "cooking pot": "cooking pot", "cooking pots": "cooking pot",
}

# Best-effort guess if not in official list
def _best_effort_name(name: str) -> str:
    # Remove "the" if present
    name = (name or "").lower().replace("the ", "").strip()
    # Normalize spaces
    name = " ".join(name.split())
    # Handle common plurals
    if name.endswith("ies"): return name[:-3] + "y"
    if name.endswith("es"):
        # boxes -> box, matches -> match
        if any(name.endswith(x) for x in ["xes", "ches", "shes"]):
            return name[:-2]
        # potatoes -> potato
        if name.endswith("oes"): return name[:-2]
        # suitcase -> suitcases (just remove s)
        if name.endswith("ses"): return name[:-1]
        return name[:-1]
    if name.endswith("s") and not name.endswith("ss"): return name[:-1]
    return name



# ════════════════════════════════════════════════════════════════════
class AmazonCaptchaSolver:
    """Minimal, efficient CAPTCHA solver tuned for Amazon CVF puzzles."""

    MAX_ATTEMPTS = 10
    GRID_SIZE = 3  # 3×3

    def __init__(self, page, device=None):
        self.page = page
        self.device = device

        # ── API keys ────────────────────────────────────────────────
        self.openai_key = os.getenv("OPENAI_API_KEY")
        self.openrouter_key = os.getenv("OPENROUTER_API_KEY")
        self.gemini_key = os.getenv("GEMINI_API_KEY")
        self.grok_key = os.getenv("GROK_API_KEY")
        self.capsolver_key = os.getenv("CAPSOLVER_API_KEY")
        self.nopecha_key = os.getenv("NOPECHA_API_KEY")

        # ── Config ──────────────────────────────────────────────────
        self.min_confidence = float(os.getenv("CAPTCHA_MIN_CONFIDENCE", "0.8"))
        self.manual_fallback = os.getenv("CAPTCHA_MANUAL_FALLBACK", "False").lower() == "true"
        self.openrouter_model = os.getenv("OPENROUTER_MODEL", "openai/gpt-4o-mini")

        # ── Clients ─────────────────────────────────────────────────
        self.openai_client = None
        self.openrouter_client = None

        if self.openai_key and openai:
            self.openai_client = openai.OpenAI(api_key=self.openai_key)

        if self.openrouter_key and openai:
            self.openrouter_client = openai.OpenAI(
                api_key=self.openrouter_key,
                base_url="https://openrouter.ai/api/v1",
            )

    # ═══════════════════════════════════════════════════════════════
    # Detection
    # ═══════════════════════════════════════════════════════════════

    def detect(self) -> Dict[str, Any]:
        """Detect CAPTCHA type, element, and instruction text."""
        checks = [
            ("amazon_audio", self._detect_amazon_audio),
            ("amazon_cvf", self._detect_amazon_cvf),
            ("amazon_text", self._detect_amazon_text),
            ("recaptcha", self._detect_recaptcha),
        ]
        for ctype, fn in checks:
            result = fn()
            if result:
                logger.info(f"Detected {ctype} CAPTCHA")
                
                # Check for "Time limit exceeded" or other errors that require refresh
                error_selectors = [
                    ".a-alert-content:has-text('Time limit exceeded')",
                    ".a-alert-content:has-text('Please try again')",
                    ".a-alert-content:has-text('System error')",
                    ":text('Incorrect. Please try again')",
                ]
                for error_sel in error_selectors:
                    try:
                        if self.page.locator(error_sel).first.is_visible(timeout=500):
                            logger.warning(f"(!) CAPTCHA Error detected: {error_sel}")
                            result["error_msg"] = "Time limit exceeded or System error or Incorrect"
                            break
                    except Exception:
                        pass

                return {"type": ctype, **result}

        return {"type": None, "element": None, "instructions": None, "target": None, "error_msg": None}

    def _detect_amazon_cvf(self) -> Optional[Dict]:
        """Amazon CVF grid puzzle ('Choose all the …')."""
        selectors = [
            ":has-text('Choose all the')",
            "span.cvf-widget-grid-item",
            ".cvf-grid-container",
        ]
        for sel in selectors:
            try:
                el = self.page.locator(sel).first
                if el.is_visible(timeout=1500):
                    target = self._extract_amazon_cvf_target()
                    instructions = f"Choose all the {target}" if target else None
                    # Get the puzzle images
                    images = self._find_puzzle_images()
                    return {
                        "element": images[0] if images else el,
                        "instructions": instructions,
                        "target": target,
                    }
            except Exception:
                continue
        return None

    def _detect_amazon_audio(self) -> Optional[Dict]:
        """Amazon/AWS WAF Audio CAPTCHA (audio element + base64 src)."""
        selectors = [
            "audio",
            ":text('Click play to listen')",
            "input#cvf-a11y-audio-input",
            ".cvf-widget-input[type='text']",
        ]
        for sel in selectors:
            try:
                el = self.page.locator(sel).first
                if el.is_visible(timeout=1500):
                    # For audio tags, is_visible might be False even if attached.
                    # We check for presence in DOM.
                    audio_el = self.page.locator("audio").first
                    if audio_el.count() > 0:
                        return {
                            "element": audio_el,
                            "instructions": "Type the characters you hear",
                            "target": "audio",
                            "type": "amazon_audio",
                        }
            except Exception:
                continue
        return None

    def _detect_amazon_text(self) -> Optional[Dict]:
        """Amazon text CAPTCHA ('Type the characters')."""
        selectors = [
            "#captcha-image",
            "img[src*='captcha']",
            "#auth-captcha-image",
        ]
        for sel in selectors:
            try:
                el = self.page.locator(sel).first
                if el.is_visible(timeout=1500):
                    return {
                        "element": el,
                        "instructions": "Type the characters you see in the image",
                        "target": None,
                    }
            except Exception:
                continue
        return None

    def _detect_recaptcha(self) -> Optional[Dict]:
        """reCAPTCHA v2 image challenge."""
        selectors = [
            "iframe[src*='recaptcha/api2/bframe']",
            "#rc-imageselect",
            "iframe[title*='challenge']",
        ]
        for sel in selectors:
            try:
                el = self.page.locator(sel).first
                if el.is_visible(timeout=1500):
                    instructions, target = self._extract_recaptcha_target()
                    return {
                        "element": el,
                        "instructions": instructions,
                        "target": target,
                    }
            except Exception:
                continue
        return None

    # ── Target extraction helpers ───────────────────────────────────

    def _extract_amazon_cvf_target(self) -> Optional[str]:
        """Parse 'Choose all the <object>' from page text."""
        try:
            body_text = self.page.inner_text("body")
            # Use [^\n] to prevent matching across newlines (avoids 'seats\nsolved')
            match = re.search(r"[Cc]hoose all the\s+([^\n]{1,40})", body_text)
            if match:
                raw_target = match.group(1).strip().lower()
                # Strip trailing noise words: solved, confirm, etc.
                raw_target = re.sub(
                    r"\s*(?:solved|confirm|click|verify|select|if there are none).*$",
                    "", raw_target, flags=re.IGNORECASE
                ).strip()
                # Remove trailing punctuation
                raw_target = raw_target.rstrip(".,;:!?")
                if raw_target:
                    logger.info(f"📋 CVF target: '{raw_target}'")
                    return raw_target
        except Exception as e:
            logger.debug(f"CVF target extraction failed: {e}")
        return None

    def _extract_recaptcha_target(self) -> tuple:
        """Extract instructions + target from reCAPTCHA bframe."""
        for f in self.page.frames:
            url = f.url or ""
            if "recaptcha" in url and "bframe" in url:
                try:
                    raw = f.locator(".rc-imageselect-instructions").inner_text()
                    instructions = raw.replace("\n", " ").strip()
                    # Parse target object
                    match = re.search(
                        r"(?:Select all (?:images|squares) with|containing)\s+(.+?)(?:\.|$)",
                        instructions, re.IGNORECASE,
                    )
                    target = match.group(1).strip().lower() if match else None
                    # Strip all trailing noise
                    if target:
                        target = re.sub(
                            r"\s*(?:if there are none|click verify|click skip|once there are none).*$",
                            "", target, flags=re.IGNORECASE
                        ).strip()
                    logger.info(f"CAPTCHA target: '{target}'")
                    return instructions, target
                except Exception:
                    pass
        return None, None

    def _find_puzzle_images(self) -> List:
        """Find the 9 images in the Amazon CVF grid."""
        selectors = [
            "div.cvf-grid-image img",
            "div.a-section:has(> img):has(> img):has(> img) img",
            "div[class*='puzzle'] img",
            "#captcha-container img",
            "form[action*='cvf'] img",
            "img[class*='tile']",
        ]
        for sel in selectors:
            try:
                imgs_list = self.page.locator(sel).all()
                if len(imgs_list) >= 9:
                    # Filter: must be visible and roughly the same size
                    valid = []
                    for im in imgs_list:
                        bx = im.bounding_box()
                        if bx and bx["width"] > 40 and bx["height"] > 40:
                            # Aspect ratio check (grid tiles are roughly square)
                            ratio = bx["width"] / bx["height"]
                            if 0.6 < ratio < 1.6:
                                valid.append(im)
                    if len(valid) >= 9:
                        return valid[:9]
            except Exception:
                continue
        return []

    def _get_grid_bbox_from_images(self, images: List) -> Optional[Dict]:
        """Compute the encompassing bounding box for a set of images."""
        if not images: return None
        bxes = []
        for im in images:
            b = im.bounding_box()
            if b: bxes.append(b)
        if not bxes: return None

        min_x = min(b["x"] for b in bxes)
        min_y = min(b["y"] for b in bxes)
        max_x = max(b["x"] + b["width"] for b in bxes)
        max_y = max(b["y"] + b["height"] for b in bxes)
        
        return {
            "x": min_x,
            "y": min_y,
            "width": max_x - min_x,
            "height": max_y - min_y
        }

    # ═══════════════════════════════════════════════════════════════
    # Screenshot
    # ═══════════════════════════════════════════════════════════════

    def _screenshot_b64(self, element=None, clip: Optional[Dict[str, float]] = None) -> str:
        """Take screenshot → base64 string. Prefers clip rect if provided."""
        if clip:
            return base64.b64encode(self.page.screenshot(clip=clip)).decode("utf-8")
        if element:
            return base64.b64encode(element.screenshot()).decode("utf-8")
        return self._screenshot_page_b64()

    def _screenshot_page_b64(self) -> str:
        """Full page screenshot → base64 string (fallback)."""
        return base64.b64encode(self.page.screenshot()).decode("utf-8")

    # ═══════════════════════════════════════════════════════════════
    # Tier 1: AI Vision
    # ═══════════════════════════════════════════════════════════════

    _AI_PROMPT = """You are an expert CAPTCHA solver specialized in Amazon CVF / AWS WAF image-selection puzzles. These are 3x3 grids (9 images) where you must select all tiles matching a single object category.

Analyze this screenshot carefully:

Step-by-step reasoning:
1. Read the exact instruction text (usually "Choose all the [OBJECT]").
2. Identify the target object category (singular/plural, e.g., "buckets", "hats", "clocks").
3. Examine each of the 9 images in the grid (numbered left-to-right, top-to-bottom: positions 1–9).
4. For each position, decide if it clearly contains the target object (even if partial, stylized, or in unusual context). Ignore close distractors (e.g., barrel ≠ bucket, bag ≠ hat).
5. Be strict: only select if you are highly confident it matches.

{extra}

Output ONLY valid JSON (no markdown fences):
{{"target": "buckets", "positions": [2, 6, 9], "coordinates": [[x1,y1], [x2,y2]], "confidence": 0.92, "reasoning": "Brief explanation"}}

IMPORTANT:
- "positions" = 1-based indices of matching tiles (1-9, left-to-right top-to-bottom)
- "coordinates" = absolute pixel coordinates from TOP-LEFT of the provided screenshot (center of each matching tile)
- If not solvable: return {{"error": "Not solvable", "confidence": 0.0}}
"""

    def _select_ai(self) -> Optional[str]:
        """Pick the best available AI backend."""
        priority = [
            ("openai", self.openai_key, self.openai_client),
            ("openrouter", self.openrouter_key, self.openrouter_client),
        ]
        for name, key, client in priority:
            if key and client:
                return name
        return None

    def _call_openai(self, prompt: str, img_b64: str) -> Dict:
        if not self.openai_client:
            return {"error": "OpenAI client not initialized"}

        resp = self.openai_client.chat.completions.create(
            model="gpt-4o",
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img_b64}"}},
                ],
            }],
            response_format={"type": "json_object"},
        )
        content = resp.choices[0].message.content
        if not content:
            return {"error": "Empty response from OpenAI"}
        return json.loads(content)

    def _call_openrouter(self, prompt: str, img_b64: str) -> Dict:
        if not self.openrouter_client:
            return {"error": "OpenRouter client not initialized"}

        resp = self.openrouter_client.chat.completions.create(
            model=self.openrouter_model,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img_b64}"}},
                ],
            }],
            # OpenRouter handles JSON format via provider-specific parameters usually, 
            # but standardizing here.
        )
        content = resp.choices[0].message.content
        if not content:
            return {"error": "Empty response from OpenRouter"}
        return json.loads(content)

    def _solve_ai(self, element, info: Dict) -> Optional[Dict]:
        """Call AI vision model and return parsed JSON response."""
        backend = self._select_ai()
        if not backend:
            logger.warning("⏭ No AI keys configured — skipping AI tier")
            return None

        logger.info(f"AI Tier: using {backend}")
        img_b64 = self._screenshot_b64(element)

        extra = ""
        if info.get("instructions"):
            extra = f'The on-screen instruction says: "{info["instructions"]}"'

        prompt = self._AI_PROMPT.format(extra=extra)

        try:
            if backend == "openai":
                return self._call_openai(prompt, img_b64)
            elif backend == "openrouter":
                return self._call_openrouter(prompt, img_b64)
        except Exception as e:
            logger.error(f"AI vision failed ({backend}): {e}")
        return None

    def _solve_capsolver(self, element, info: Dict) -> bool:
        """Use Capsolver classification API."""
        if not self.capsolver_key:
            logger.warning("⏭ No Capsolver key — skipping API tier")
            return False

        ctype = info["type"]
        target = info.get("target", "")

        # Target 9 images directly for perfect alignment
        images = self._find_puzzle_images()
        if not images:
            logger.warning("Could not find 9 grid images — falling back to container screenshot")
            img_b64 = self._screenshot_b64(element)
            bbox = None
        else:
            bbox = self._get_grid_bbox_from_images(images)
            if bbox:
                logger.debug(f"📐 Detected precise grid bbox: {bbox}")
                img_b64 = self._screenshot_b64(clip=bbox)
            else:
                img_b64 = self._screenshot_b64(element)

        # Validate screenshot (ensure we didn't get a 1px line or stale element)
        if Image is not None:
            try:
                img_bytes = base64.b64decode(img_b64)
                img = Image.open(BytesIO(img_bytes))
                w, h = img.size
                if h < 100:
                    logger.warning(f"Screenshot suspiciously small ({w}x{h}) — trying page fallback")
                    img_b64 = self._screenshot_page_b64()
            except Exception as e:
                logger.debug(f"Screenshot validation error: {e}")

        try:
            if ctype == "amazon_cvf":
                return self._capsolver_aws_waf(img_b64, target or "", images)
            elif ctype == "recaptcha":
                if capsolver:
                    capsolver.api_key = self.capsolver_key
                return self._capsolver_recaptcha(img_b64, target or "", element)
            elif ctype == "amazon_text":
                return self._capsolver_image_to_text(img_b64)
        except Exception as e:
            logger.error(f"Capsolver API failed: {e}")
        return False

    def _capsolver_aws_waf(self, img_b64: str, target: str, tile_locators: Optional[List[Any]] = None) -> bool:
        """AwsWafClassification — split grid into tiles and classify."""
        # Clean target
        clean_target = (target or "").replace("\n", " ").strip().lower()
        clean_target = _best_effort_name(clean_target)

        # Map to Capsolver's supported singular form
        capsolver_obj = AWS_WAF_SUPPORTED_OBJECTS.get(clean_target, clean_target)

        question = AWS_WAF_QUESTION_FMT.format(obj=capsolver_obj)
        logger.info(f"Capsolver AwsWafClassification - question='{question}'")

        # Split grid image into individual tiles for better recognition
        tile_images = self._split_grid_to_tiles(img_b64)
        if not tile_images:
            logger.warning("Failed to split grid — sending full image")
            tile_images = [img_b64]

        logger.info(f"📤 Sending {len(tile_images)} tile(s) to Capsolver")

        # Use direct HTTP API (synchronous — returns results immediately)
        solution = self._capsolver_http_classify(tile_images, question)
        if solution is not None:
            return self._apply_capsolver_grid_result(solution, tile_locators)

        # Fallback to SDK if HTTP failed
        if capsolver:
            try:
                capsolver.api_key = self.capsolver_key
                sdk_result = capsolver.solve({
                    "type": "AwsWafClassification",
                    "images": tile_images,
                    "question": question,
                })
                logger.info(f"📦 Capsolver SDK fallback response: {sdk_result}")
                if sdk_result:
                    return self._apply_capsolver_grid_result(sdk_result, element)
            except Exception as e:
                logger.error(f"Capsolver SDK fallback error: {e}")
        return False

    def _capsolver_http_classify(self, images: list, question: str) -> Optional[Dict]:
        """Direct HTTP call to Capsolver createTask (synchronous classification).
        
        Per docs: Classification tasks return results immediately in createTask response
        when status='ready'. No getTaskResult polling needed.
        """
        try:
            payload = {
                "clientKey": self.capsolver_key,
                "task": {
                    "type": "AwsWafClassification",
                    "images": images,
                    "question": question,
                }
            }
            
            resp = requests.post(
                "https://api.capsolver.com/createTask",
                json=payload,
                timeout=30,
            )
            data = resp.json()
            
            error_id = data.get("errorId", 0)
            error_code = data.get("errorCode", "")
            
            if error_id > 0:
                logger.error(f"Capsolver API error: {error_code} — {data.get('errorDescription', '')}")
                if error_code in ("ERROR_RATE_LIMIT", "ERROR_SETTIMEOUT"):
                    logger.info("Rate limited — waiting 3s")
                    time.sleep(3)
                return None
            
            status = data.get("status", "")
            if status == "ready":
                solution = data.get("solution", {})
                logger.success(f"Capsolver HTTP response: {solution}")
                return solution
            else:
                logger.warning(f"Capsolver status={status}, expected 'ready' for sync task")
                return None
                
        except requests.exceptions.Timeout:
            logger.error("Capsolver HTTP request timed out (30s)")
            return None
    def _solve_nopecha(self, element, info: Dict) -> bool:
        """Attempt to solve using Nopecha."""
        if not self.nopecha_key:
            return False

        ctype = info.get("type")
        if ctype == "amazon_cvf":
            return self._nopecha_awscaptcha(element, info)
        elif ctype == "amazon_audio":
            return self._nopecha_awscaptcha_audio(element, info)
        return False

    def _nopecha_awscaptcha_audio(self, element, info: Dict) -> bool:
        """Solve AWS WAF Audio using Nopecha Recognition API (Two-step: POST -> POLL)."""
        try:
            logger.info("Nopecha AWS Audio CAPTCHA recognition (POST + POLL)...")
            
            # Extract full base64 src (with prefix) for POST as an array
            src = element.get_attribute("src")
            if not src or "base64," not in src:
                logger.warning("Nopecha: No valid audio src found")
                return False
            
            url = "https://api.nopecha.com/v1/recognition/awscaptcha"
            headers = {"Authorization": f"Basic {self.nopecha_key}"}
            payload = {
                "audio_data": [src] # Must be a list with prefix
            }
            
            # 1. Submit Job
            resp = requests.post(url, headers=headers, json=payload, timeout=30)
            post_data = resp.json()
            job_id = post_data.get("data")
            
            if not job_id:
                logger.error(f"Nopecha Audio submission failed: {post_data}")
                return False
                
            logger.debug(f"Nopecha Job ID: {job_id} - Polling for result...")
            
            # 2. Poll for Result
            max_polls = 10
            poll_interval = 2.0
            
            for i in range(max_polls):
                time.sleep(poll_interval)
                poll_resp = requests.get(url, params={"id": job_id}, headers=headers, timeout=10)
                poll_data = poll_resp.json()
                
                # AWS Audio usually returns ["text"]
                if "data" in poll_data and poll_data["data"]:
                    results = poll_data["data"]
                    text_result = results[0] if isinstance(results, list) else results
                    
                    if text_result and text_result != "pending":
                        logger.success(f"Nopecha Audio solved: {text_result}")
                        
                        # Type into input field
                        input_sel = "input[type='text'], #cvf-a11y-audio-input, .cvf-widget-input"
                        inp = self.page.locator(input_sel).first
                        if inp.count() > 0:
                            inp.fill(text_result)
                            time.sleep(random.uniform(0.5, 1.0))
                            self._click_confirm()
                            return True

                logger.debug(f"Poll {i+1}/{max_polls}: still pending...")
            
            logger.warning(f"Nopecha Audio solve timed out or failed: {post_data}")
        except Exception as e:
            logger.error(f"Nopecha Audio failure: {e}")
        return False

    def _nopecha_awscaptcha(self, element, info: Dict) -> bool:
        """Solve AWS WAF Grid using Nopecha Recognition API."""
        try:
            target = info.get("target", "")
            logger.info(f"Nopecha AWS CAPTCHA recognition - target: {target}")

            # Find tiles or fallback to grid split
            locators = self._find_puzzle_images()
            images_b64 = []
            if locators and len(locators) >= 9:
                for loc in locators:
                    images_b64.append(self._screenshot_b64(loc))
            else:
                # Fallback to splitting the main element screenshot
                full_b64 = self._screenshot_b64(element)
                if full_b64:
                    images_b64 = self._split_grid_to_tiles(full_b64)

            if not images_b64:
                logger.warning("Nopecha: Could not prepare tile images")
                return False

            url = "https://api.nopecha.com/v1/recognition/awscaptcha"
            headers = {"Authorization": f"Basic {self.nopecha_key}"}
            payload = {
                "image_data": images_b64,
                "task": target or "select objects",
                "grid": "3x3"
            }
            
            resp = requests.post(url, headers=headers, json=payload, timeout=30)
            data = resp.json()
            
            if "data" in data:
                # Nopecha returns [true, false, ...] for grid
                solution = data["data"]
                if isinstance(solution, list):
                    indices = [i for i, val in enumerate(solution) if val is True]
                    return self._apply_capsolver_grid_result({"objects": indices}, element, locators)
            
            logger.warning(f"Nopecha AWS WAF solve unsuccessful: {data}")
        except Exception as e:
            logger.error(f"Nopecha AWS WAF failure: {e}")
        return False

    def _split_grid_to_tiles(self, grid_b64: str) -> list:
        """Split a 3x3 grid image into 9 individual base64 tile images."""
        try:
            if not Image:
                logger.error("PIL (Pillow) not installed — cannot split grid")
                return []
            img_bytes = base64.b64decode(grid_b64)
            img = Image.open(BytesIO(img_bytes))
            w, h = img.size
            tile_w = w // 3
            tile_h = h // 3
            tiles = []
            for row in range(3):
                for col in range(3):
                    box = (col * tile_w, row * tile_h, (col + 1) * tile_w, (row + 1) * tile_h)
                    tile = img.crop(box)
                    buf = BytesIO()
                    tile.save(buf, format="PNG")
                    tiles.append(base64.b64encode(buf.getvalue()).decode("utf-8"))
            logger.debug(f"Split grid ({w}x{h}) into {len(tiles)} tiles ({tile_w}x{tile_h} each)")
            return tiles
        except Exception as e:
            logger.error(f"Grid splitting failed: {e}")
            return []

    def _capsolver_recaptcha(self, img_b64: str, target: str, element) -> bool:
        """ReCaptchaV2Classification — classify each tile individually."""
        # Normalize target: strip noise, articles, lowercase
        clean = (target or "").strip().lower()
        clean = re.sub(
            r"\s*(?:if there are none|click verify|click skip|once there are none).*$",
            "", clean, flags=re.IGNORECASE
        ).strip()
        clean = re.sub(r"^(?:a|an|the)\s+", "", clean).strip()

        question_id = RECAPTCHA_QUESTION_IDS.get(clean, "")
        if not question_id:
            question_id = RECAPTCHA_QUESTION_IDS.get(clean.rstrip("s"), "")
        if not question_id:
            logger.warning(f"No Capsolver question ID for '{clean}' — skipping Capsolver")
            return False

        # Get the GRID screenshot from inside the iframe
        grid_screenshot = None
        for f in self.page.frames:
            url = f.url or ""
            if "recaptcha" in url and "bframe" in url:
                try:
                    grid_el = f.locator(".rc-imageselect-target, table.rc-imageselect-table, #rc-imageselect-target").first
                    if grid_el.is_visible(timeout=2000):
                        grid_screenshot = grid_el.screenshot()
                        logger.info("📸 Captured grid screenshot for Capsolver")
                        break
                except Exception as e:
                    logger.debug(f"Could not capture grid: {e}")

        if not grid_screenshot:
            logger.warning("Could not capture grid screenshot — skipping Capsolver")
            return False

        # Split grid into 9 individual tiles using PIL
        try:
            from io import BytesIO
            from PIL import Image

            grid_img = Image.open(BytesIO(grid_screenshot))
            w, h = grid_img.size
            tile_w = w // 3
            tile_h = h // 3

            matching_positions = []
            logger.info(f"🔧 Capsolver classifying 9 tiles — target='{clean}' question='{question_id}'")

            for idx in range(9):
                row = idx // 3
                col = idx % 3
                left = col * tile_w
                top = row * tile_h
                right = left + tile_w
                bottom = top + tile_h

                tile = grid_img.crop((left, top, right, bottom))
                buf = BytesIO()
                tile.save(buf, format="PNG")
                tile_b64 = base64.b64encode(buf.getvalue()).decode("utf-8")

                try:
                    solution = capsolver.solve({
                        "type": "ReCaptchaV2Classification",
                        "image": tile_b64,
                        "question": question_id,
                    })

                    has_obj = solution.get("hasObject", False)
                    logger.debug(f"Tile {idx+1}: hasObject={has_obj}")
                    if has_obj:
                        matching_positions.append(idx + 1)
                except Exception as e:
                    logger.debug(f"Tile {idx+1} classification error: {e}")

            if matching_positions:
                logger.success(f"🎯 Capsolver found matches at positions: {matching_positions}")
                self._click_tiles(matching_positions, element)
                return True
            else:
                logger.info("Capsolver found no matching tiles")
                return False

        except ImportError:
            logger.error("PIL/Pillow not installed — cannot split grid for Capsolver")
            return False
        except Exception as e:
            logger.error(f"Capsolver grid classification error: {e}")
            return False

    def _capsolver_image_to_text(self, img_b64: str) -> bool:
        """Simple image-to-text for Amazon text CAPTCHAs."""
        solution = capsolver.solve({
            "type": "ImageToTextTask",
            "body": img_b64,
        })
        if solution and solution.get("text"):
            text = solution["text"]
            logger.success(f"Capsolver text CAPTCHA: '{text}'")
            inp = self.page.locator("#captchacharacters, #auth-captcha-guess, input[name='cvf_captcha_input']").first
            inp.fill(text)
            # Submit
            for sel in ["button:has-text('Continue')", "button[type='submit']", "input[type='submit']"]:
                try:
                    btn = self.page.locator(sel).first
                    if btn.is_visible(timeout=1000):
                        btn.click()
                        break
                except Exception:
                    continue
            return True
        return False

    def _apply_capsolver_grid_result(self, solution: Dict, element, locators: Optional[List] = None) -> bool:
        """Click tiles based on Capsolver response."""
        result = solution.get("objects", solution.get("solution", []))
        if not result:
            logger.warning("Capsolver returned no objects/solution to click")
            return False

        indices = [i for i in result if isinstance(i, int)]
        if not indices:
            logger.info("Capsolver: no matching tiles to click")
            return False

        # 1-based labels for logging
        logger.success(f"Clicking tiles at mapping: {[i+1 for i in indices]}")

        if locators and len(locators) >= 9:
            # Atomic clicks using MOUSE on verified elements
            for idx in indices:
                if 0 <= idx < len(locators):
                    bx = locators[idx].bounding_box()
                    if bx:
                        cx = bx["x"] + bx["width"] / 2
                        cy = bx["y"] + bx["height"] / 2
                        time.sleep(random.uniform(0.15, 0.35))
                        self.page.mouse.click(cx, cy)
                        logger.debug(f"Clicked element index {idx} at ({cx:.0f}, {cy:.0f})")
            
            # Submission logic
            time.sleep(random.uniform(1.2, 2.0))
            self._click_confirm()
            return True
        else:
            # COORDINATE MATH FALLBACK using the element bounding box
            logger.warning("No locators found for click — using coordinate math fallback")
            self._click_tiles(indices, element)
            return True

    # ═══════════════════════════════════════════════════════════════
    # Tier 3: Manual Fallback
    # ═══════════════════════════════════════════════════════════════

    def _solve_manual(self, ctype: str) -> bool:
        """Wait for human to solve, OR auto-retry Capsolver when puzzle rotates to supported object."""
        if not self.manual_fallback:
            logger.warning(f"Manual fallback disabled — cannot solve {ctype}")
            return False

        logger.warning(f"🖐 MANUAL FALLBACK: {ctype} — solve in browser window")
        print(f"\n{'='*60}")
        print(f"  [!!!] CAPTCHA MANUAL SOLVE REQUIRED: {ctype}")
        print(f"{'='*60}")
        print("  Waiting up to 2 minutes — will auto-resume when solved.")
        print("  Will also auto-retry Capsolver if puzzle changes to supported object.\n\a")

        deadline = time.time() + 120
        last_target = None
        while time.time() < deadline:
            info = self.detect()
            if not info["type"]:
                logger.success("✓ CAPTCHA solved manually")
                return True
            
            # If error message appeared, exit manual and let solve() handle refresh
            if info.get("error_msg"):
                logger.warning(f"Exiting manual phase due to error: {info['error_msg']}")
                return False

            # Check if target changed to something Capsolver can handle
            current_target = info.get("target", "")
            if current_target and current_target != last_target:
                last_target = current_target
                clean = current_target.lower().strip()
                # Check mapping
                supported = AWS_WAF_SUPPORTED_OBJECTS.get(clean)
                if supported and self.capsolver_key:
                    logger.info(f"Puzzle rotated to '{current_target}' (supported!) - auto-retrying Capsolver")
                    if self._solve_capsolver(info["element"], info):
                        self._click_confirm()
                        time.sleep(3)
                        post = self.detect()
                        if not post["type"]:
                            logger.success("Solved via Capsolver during manual wait!")
                            return True
                        logger.warning("Capsolver retry during manual wait failed — continuing wait")

            time.sleep(2)

        logger.error("Manual solve timed out (2 min)")
        return False

    # ═══════════════════════════════════════════════════════════════
    # Click simulation
    # ═══════════════════════════════════════════════════════════════

    def _click_tiles(self, indices: List[int], element):
        """Click grid tiles by 0-based indices using coordinate math."""
        box = element.bounding_box()
        if not box:
            logger.error("Cannot get bounding box for tile calculation")
            return

        tile_w = box["width"] / self.GRID_SIZE
        tile_h = box["height"] / self.GRID_SIZE

        for idx in indices:
            row = idx // self.GRID_SIZE
            col = idx % self.GRID_SIZE
            cx = box["x"] + col * tile_w + tile_w / 2 + random.randint(-2, 2)
            cy = box["y"] + row * tile_h + tile_h / 2 + random.randint(-2, 2)

            self.page.mouse.move(cx, cy, steps=random.randint(5, 12))
            time.sleep(random.uniform(0.15, 0.35))
            logger.debug(f"Clicking index {idx} at ({cx:.0f}, {cy:.0f})...")
            self.page.mouse.click(cx, cy)
            logger.debug(f"Clicked index {idx}")
            time.sleep(random.uniform(0.25, 0.55))

    def _click_coordinates(self, coords: List[List[int]], element):
        """Click absolute pixel coordinates relative to element."""
        box = element.bounding_box()
        if not box:
            return

        for x, y in coords:
            tx = box["x"] + x + random.randint(-3, 3)
            ty = box["y"] + y + random.randint(-3, 3)

            self.page.mouse.move(tx, ty, steps=random.randint(5, 12))
            time.sleep(random.uniform(0.15, 0.35))
            self.page.mouse.click(tx, ty)
            logger.debug(f"Clicked coord ({tx:.0f}, {ty:.0f})")
            time.sleep(random.uniform(0.25, 0.55))

        # After clicking all tiles, wait a bit for the UI to register them
        time.sleep(random.uniform(0.5, 1.0))
        self._click_confirm()

    def _switch_to_audio(self) -> bool:
        """Switch from grid puzzle to audio mode (handles iframes)."""
        try:
            selectors = [
              '//*[@id="amzn-btn-audio-internal"]', # Specific user XPath
              "#cvf-a11y-audio-link",
              "#cvf-a11y-audio-input",
              "a:has-text('Audio')",
              "button.cvf-audio-button",
              "i.a-icon-headphones",
            ]
            
            # 1. Try main page
            for sel in selectors:
                btn = self.page.locator(sel).first
                if btn.count() > 0:
                    try:
                        # Attempt JS click for speed and reliability
                        btn.evaluate("el => el.click()")
                        logger.info(f"Switching to Audio CAPTCHA mode via {sel} (JS Click)")
                        time.sleep(2)
                        return True
                    except Exception:
                        # Native fallback
                        if btn.is_visible(timeout=500):
                            logger.info(f"Switching to Audio CAPTCHA mode via {sel} (Native)")
                            btn.click(timeout=5000)
                            time.sleep(2)
                            return True
            
            # 2. Search in all iframes
            for frame in self.page.frames:
                for sel in selectors:
                    try:
                        btn = frame.locator(sel).first
                        if btn.count() > 0:
                            btn.evaluate("el => el.click()")
                            logger.info(f"Switching to Audio CAPTCHA mode via {sel} (Frame JS)")
                            time.sleep(2)
                            return True
                    except Exception:
                        continue
        except Exception as e:
            logger.debug(f"Could not switch to audio: {e}")
        return False

    def _click_confirm(self):
        """Click Confirm / Verify / Submit button (including inside iframes)."""
        # First try inside reCAPTCHA / hCaptcha iframes
        for f in self.page.frames:
            url = f.url or ""
            if "recaptcha" in url or "hcaptcha" in url:
                try:
                    # Wait for the button to be visible and enabled
                    btn = f.locator("button#recaptcha-verify-button, .rc-button-default, button:has-text('Verify'), button:has-text('Skip'), button:has-text('Next')").first
                    if btn.is_visible(timeout=1000):
                        time.sleep(random.uniform(0.3, 0.7))
                        btn.click()
                        logger.debug(f"Clicked confirm inside iframe: {url[:50]}")
                        return
                except Exception:
                    continue

        # Then try main page
        confirm_selectors = [
            "button:has-text('Confirm')",
            "button:has-text('Verify')",
            "button:has-text('Next')",
            "button:has-text('Skip')",
            "input[type='submit']",
        ]
        for sel in confirm_selectors:
            try:
                btn = self.page.locator(sel).first
                if btn.is_visible(timeout=1000):
                    time.sleep(random.uniform(0.3, 0.7))
                    btn.click()
                    logger.debug(f"Clicked confirm: {sel}")
                    return
            except Exception:
                continue

    # ═══════════════════════════════════════════════════════════════
    # Main solve loop
    # ═══════════════════════════════════════════════════════════════

    def solve(self) -> bool:
        """Run the full tiered solve with retry."""
        for attempt in range(1, self.MAX_ATTEMPTS + 1):
            info = self.detect()
            if not info["type"]:
                logger.success("No CAPTCHA present — proceeding")
                return True

            ctype = info["type"]
            element = info["element"]
            
            # ────────────────────────────────────────────────────────
            # 🚀 TIER 0: Nopecha (Highly Priority - Grid & Audio)
            # ────────────────────────────────────────────────────────
            if self.nopecha_key and info["type"] in ["amazon_cvf", "amazon_audio"]:
                # 1. Proactively switch from Grid to Audio for better success
                if info["type"] == "amazon_cvf":
                    logger.info("⚡ Priority: Attempting switch to Audio mode (Nopecha Optimized)")
                    if self._switch_to_audio():
                        time.sleep(1)
                        info = self.detect() # Re-detect as audio
                
                # 2. Solve via Nopecha (Audio or Grid)
                element = info.get("element", element)
                logger.info(f"Nopecha Solving Tier (Attempt {attempt}): {info['type']}")
                if self._solve_nopecha(element, info):
                    time.sleep(1)
                    if not self.detect()["type"]:
                        logger.success(f"✅ Resolved via Nopecha Priority Tier")
                        return True
            
            # ────────────────────────────────────────────────────────
            # 📷 Tier 1: AI Vision (Fallback)
            # ────────────────────────────────────────────────────────
            ai_result = self._solve_ai(element, info)
            if ai_result and not ai_result.get("error"):
                conf = ai_result.get("confidence", 0)
                logger.info(f"💡 AI confidence={conf} | reasoning={ai_result.get('reasoning', '')[:80]}")

                if conf >= self.min_confidence:
                    if ai_result.get("positions"):
                        self._click_tiles(ai_result["positions"], element)
                    elif ai_result.get("coordinates"):
                        self._click_coordinates(ai_result["coordinates"], element)
                    elif ai_result.get("clicks"):
                        self._click_coordinates(ai_result["clicks"], element)

                    self._click_confirm()
                    time.sleep(3)

                    # Check if solved
                    post = self.detect()
                    if not post["type"]:
                        logger.success(f"✅ Solved via AI on attempt {attempt}")
                        return True
                    logger.warning("AI clicked but CAPTCHA still present — wrong answer, retrying")
                    # Re-detect since grid changed after wrong answer
                    info = self.detect()
                    element = info.get("element", element)
                else:
                    logger.warning(f"AI confidence {conf} < {self.min_confidence} — skipping AI")

            # ── Tier 2: Capsolver ───────────────────────────────────
            # Try Capsolver (possibly on a fresh puzzle if AI failed)
            capsolver_tries = 0
            max_capsolver_tries = 3
            while capsolver_tries < max_capsolver_tries and info.get("type"):
                capsolver_tries += 1
                # CRITICAL: Re-detect element each time to avoid stale reference
                info = self.detect()
                if not info.get("type"):
                    logger.success("CAPTCHA solved between retries!")
                    return True
                element = info.get("element", element)
                logger.info(f"Capsolver try {capsolver_tries}/{max_capsolver_tries} for {info['type']} (target: {info.get('target', '?')})")
                if self._solve_capsolver(element, info):
                    # Check if solved
                    time.sleep(1)
                    if not self.detect()["type"]:
                        return True
                
                # If Capsolver failed and it hasn't been solved, try remaining attempts in Tier 0
                break
                
                # If still on grid, try switching to audio in the next loop or here
                if info["type"] == "amazon_cvf":
                    if self._switch_to_audio():
                        time.sleep(1)
                        continue # Re-run from detection as audio
                    break
                else: 
                    break

            # ── Tier 3: Manual ──────────────────────────────────────
            if self._solve_manual(ctype):
                return True

            # If we reach here, none of the tiers worked this attempt
            logger.warning(f"Attempt {attempt} failed — refreshing puzzle")
            self._try_refresh_puzzle()
            time.sleep(2)

        logger.error(f"❌ CAPTCHA not solved after {self.MAX_ATTEMPTS} attempts")
        return False

    def _stealth_warmup(self):
        """Subtle pre-solve actions to look more human."""
        try:
            vw = self.page.viewport_size
            if vw:
                for _ in range(random.randint(1, 3)):
                    x = random.randint(50, vw["width"] - 50)
                    y = random.randint(50, vw["height"] - 50)
                    self.page.mouse.move(x, y, steps=random.randint(8, 20))
                    time.sleep(random.uniform(0.2, 0.6))
        except Exception:
            pass

    def _try_refresh_puzzle(self):
        """Click the refresh / reload button if visible."""
        refresh_selectors = [
            "button#recaptcha-reload-button",
            "button:has-text('↻')",
            "button[aria-label='Get a new challenge']",
            ".rc-button-reload",
        ]
        for sel in refresh_selectors:
            try:
                btn = self.page.locator(sel).first
                if btn.is_visible(timeout=500):
                    btn.click()
                    time.sleep(2)
                    return
            except Exception:
                continue


# ════════════════════════════════════════════════════════════════════
# Public API (backwards-compatible)
# ════════════════════════════════════════════════════════════════════

def solve_captcha(page, device=None) -> bool:
    """Drop-in wrapper for external callers."""
    solver = AmazonCaptchaSolver(page, device)
    return solver.solve()
