import os
import json
import numpy as np
import random
from pathlib import Path
from loguru import logger
from psd_tools import PSDImage
from PIL import Image, ImageDraw, ImageFont, ImageOps, ImageFilter, ImageEnhance
from typing import Dict, Optional, Tuple, Any, List

# Background removal for ID integration
try:
    from rembg import remove as remove_bg
except ImportError:
    remove_bg = None

class DLFactory:
    """
    DLFactory: A high-fidelity Driving License generator.
    
    This factory automatically DISCOVERS placeholder layers (e.g., 'SANTA CLAUS')
    in any PSD template and REPLACES them with the same style and size.
    
    The original text is completely HIDDEN to ensure no overlaps.
    """
    def __init__(self, config_path: str = "/Users/elias/Documents/GitHub/amazon/configs/dl_templates.json"):
        self.base_dir = Path("/Users/elias/Documents/GitHub/amazon/data/DL")
        self.images_dir = self.base_dir / "images"
        self.output_dir = Path("/Users/elias/Documents/GitHub/amazon/outputs/dl")
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.config = self._load_config(config_path)

    def _load_config(self, path: str) -> Dict:
        if not os.path.exists(path):
            logger.error(f"Config not found at {path}")
            return {}
        with open(path, "r") as f:
            return json.load(f)

    def _get_template_path(self, country_code: str, side: str = "FRONT") -> Optional[Path]:
        country_code = country_code.upper()
        search_terms = {country_code}
        for key, data in self.config.items():
            if country_code == key or country_code in data.get("alias", []):
                search_terms.add(key)
                search_terms.update(data.get("alias", []))
                break
        
        for folder in self.base_dir.iterdir():
            if folder.is_dir() and any(term.upper() in folder.name.upper() for term in search_terms):
                psds = list(folder.glob("**/*.psd"))
                if not psds: continue
                side_psds = [p for p in psds if side.upper() in p.name.upper()]
                if not side_psds:
                    side_psds = [p for p in psds if "BACK" not in p.name.upper()] if side == "FRONT" else psds
                if not side_psds: return psds[0]
                side_psds.sort(key=lambda p: str(p), reverse=True)
                return side_psds[0]
        return None

    def _get_font(self, country_folder: Path, font_name: str, size: int) -> ImageFont.FreeTypeFont:
        """Load font with intelligent searching in local and global template directories."""
        # 1. Try local Font folder
        font_path = country_folder / "Font" / font_name
        if font_path.exists(): 
            return ImageFont.truetype(str(font_path), size)
        
        # 2. Search GLOBALLY in the base DL directory
        try:
            # Recursive glob can be slow, but we need it since fonts can be in nested folders
            global_path = next(self.base_dir.glob(f"**/{font_name}"), None)
            if global_path: 
                logger.info(f"Loaded font '{font_name}' from: {global_path.parent.name}")
                return ImageFont.truetype(str(global_path), size)
        except Exception: 
            pass
            
        logger.warning(f"Font '{font_name}' missing, using fallback.")
        return ImageFont.load_default()

    def _get_random_photo(self) -> Optional[str]:
        """Get path to a random photo from the images directory."""
        if not self.images_dir.exists():
            return None
        photos = [f for f in self.images_dir.iterdir() if f.suffix.lower() in [".png", ".jpg", ".jpeg"]]
        if not photos:
            return None
        import random
        choice = str(random.choice(photos))
        return choice

    def _get_random_bg(self, width: int, height: int) -> Optional[Image.Image]:
        """Load a random desk/scene background from data/DL/bg/, resized to canvas dims."""
        bg_dir = self.base_dir / "bg"
        if not bg_dir.exists():
            return None
        images = [f for f in bg_dir.iterdir() if f.suffix.lower() in [".jpg", ".jpeg", ".png"]]
        if not images:
            return None
        choice = random.choice(images)
        bg = Image.open(str(choice)).convert("RGBA")
        # Fill-crop to exact canvas size preserving aspect ratio
        bg = ImageOps.fit(bg, (width, height), method=Image.Resampling.LANCZOS)
        # Very subtle darkening so the card pops
        bg = ImageEnhance.Brightness(bg).enhance(0.82)
        logger.info(f"Using scene background: {choice.name}")
        return bg

    def _apply_bg(self, card: Image.Image, width: int, height: int) -> Image.Image:
        """Composite card RGBA over a random desk background."""
        bg = self._get_random_bg(width, height)
        if not bg:
            return card
        card_rgba = card.convert("RGBA")
        bg.paste(card_rgba, (0, 0), card_rgba)
        return bg

    def _prepare_photo(self, photo_path: str, width: int, height: int, country: str = "GB") -> Image.Image:
        """Process photo with background removal and authentic ID thermal grain."""
        # 1. Load and Background Removal
        img = Image.open(photo_path).convert("RGBA")
        
        # Proactively remove the background so it 'fits in' the ID card background
        if remove_bg:
            try:
                logger.info(f"Removing background for portrait: {Path(photo_path).name}")
                img = remove_bg(img)
            except Exception as e:
                logger.warning(f"Background removal failed: {e}")
        
        # 2. Fit and Scale
        img = ImageOps.fit(img, (width, height), method=Image.Resampling.LANCZOS)
        
        # 3. ID Print Pattern (DPI Simulation / Structured Dot Grain)
        # Create a structured dot grid common in card printing
        dot_overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        d_draw = ImageDraw.Draw(dot_overlay)
        step = 2 # 2px grid for the 'dot' look
        for y in range(0, height, step):
            for x in range(0, width, step):
                if random.random() > 0.6: # Structured but with slight randomness
                    alpha = random.randint(3, 12)
                    d_draw.point((x, y), fill=(0, 0, 0, alpha))
        
        img = Image.alpha_composite(img, dot_overlay)
        
        # 4. Color Grading for Plastic Print
        # Real IDs are slightly less colorful and have higher contrast
        img = ImageEnhance.Color(img).enhance(0.85)
        img = ImageEnhance.Brightness(img).enhance(1.05)
        img = ImageEnhance.Contrast(img).enhance(1.1)

        # 5. Country Specific Tinting
        if country == "AU":
            # AU licenses often have a very subtle warm/yellowish tint on the portrait
            overlay = Image.new("RGBA", (width, height), (255, 245, 200, 10))
            img = Image.alpha_composite(img, overlay)

        # 6. Edge Softening (Ink blend into the plastic)
        mask = Image.new("L", (width, height), 0)
        draw = ImageDraw.Draw(mask)
        draw.rectangle([2, 2, width-3, height-3], fill=255)
        mask = mask.filter(ImageFilter.GaussianBlur(radius=1.2))
        
        alpha = img.split()[-1]
        new_alpha = Image.composite(alpha, Image.new("L", (width, height), 0), mask)
        img.putalpha(new_alpha)

        return img

    def _generate_signature(self, name: str, country_folder: Path, font_config: Dict, width: int, height: int) -> Image.Image:
        # Create a larger canvas to avoid clipping during rotation
        canvas_w, canvas_h = width * 3, height * 3
        temp_img = Image.new("RGBA", (canvas_w, canvas_h), (255, 255, 255, 0))
        draw = ImageDraw.Draw(temp_img)
        
        font = self._get_font(country_folder, font_config["name"], font_config["size"])
        text = name.title()
        
        # Get true bounding box of the text
        bbox = draw.textbbox((0, 0), text, font=font)
        text_w = bbox[2] - bbox[0]
        text_h = bbox[3] - bbox[1]
        
        # Center on large canvas
        x = (canvas_w - text_w) // 2 - bbox[0]
        y = (canvas_h - text_h) // 2 - bbox[1]
        
        # Draw text (opaque black ink for better visibility)
        color = font_config.get("fill", (0, 0, 0, 255))
        draw.text((x, y), text, font=font, fill=color)
        
        # Rotate slightly for authentic handwriting look
        import random
        angle = random.uniform(-1, 5) # slight upward slant
        rotated = temp_img.rotate(angle, resample=Image.Resampling.BICUBIC, expand=True)
        
        # Crop to tight bounding box of the visible pixels
        ink_box = rotated.getbbox()
        if ink_box:
            rotated = rotated.crop(ink_box)
            
        # Resize and pad to fit target bounding box with transparent background
        from PIL import ImageOps
        final_img = ImageOps.pad(rotated, (width, height), method=Image.Resampling.LANCZOS, color=(255, 255, 255, 0))
        return final_img

    def _apply_card_texture(self, img: Image.Image) -> Image.Image:
        """Apply global effects to make the digital image look like a physical card."""
        # 1. Very subtle global grain
        width, height = img.size
        noise = np.random.randint(0, 8, (height, width, 3), dtype='uint8')
        noise_img = Image.fromarray(noise, 'RGB').convert('RGBA')
        img = Image.blend(img, Image.alpha_composite(img.convert("RGBA"), noise_img), 0.05)
        
        # 2. Plastic Reflection Shine
        # Create a diagonal soft white gradient
        shine = Image.new("RGBA", (width, height), (255, 255, 255, 0))
        shine_draw = ImageDraw.Draw(shine)
        # Draw a semi-transparent white polygon for 'gleam'
        shine_draw.polygon([(0, 0), (width//2, 0), (width, height//2), (width, height), (width//2, height), (0, height//2)], fill=(255, 255, 255, 5))
        shine = shine.filter(ImageFilter.GaussianBlur(radius=50))
        img.paste(shine, (0, 0), shine)
        
        # 3. Soften the whole image slightly (physical print look)
        img = img.filter(ImageFilter.UnsharpMask(radius=1, percent=50, threshold=3))
        
        # 4. Micro-scratches/Wear (Very faint)
        # Create a scratch overlay
        scratch_img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        s_draw = ImageDraw.Draw(scratch_img)
        import random
        for _ in range(15):
            x1 = random.randint(0, width)
            y1 = random.randint(0, height)
            x2 = x1 + random.randint(-100, 100)
            y2 = y1 + random.randint(-20, 20)
            s_draw.line([(x1, y1), (x2, y2)], fill=(255, 255, 255, 3), width=1)
        img.paste(scratch_img, (0, 0), scratch_img)
        
        return img

    def create_license(self, identity: Dict[str, Any]) -> Optional[str]:
        country_code = identity.get("country", "GB").upper()
        country_config = None
        resolved_code = country_code
        for key, data in self.config.items():
            if country_code == key or country_code in data.get("alias", []):
                country_config = data
                resolved_code = key
                break
        if not country_config: return None

        template_psd = self._get_template_path(resolved_code)
        if not template_psd: return None
            
        logger.info(f"Replacing PSD Text on: {template_psd.name}")
        psd = PSDImage.open(template_psd)
        
        # 0. RESOLVE and HIDE
        # First, hide ALL descendants except things that look like background
        for layer in psd.descendants():
            # If it's a layer we want to keep (bg), leave it.
            # Usually 'bg' or 'Layer 3' or the bottom-most pixel layer.
            if layer.kind in ['type', 'pixel', 'smartobject'] and 'BG' not in layer.name.upper():
                 layer.visible = False

        # Determine Resolution/Version
        version_cfg = None
        for vname, vdata in country_config.get("versions", {}).items():
            if vdata.get("min_width", 0) <= psd.width <= vdata.get("max_width", 99999):
                version_cfg = vdata
                break
        if not version_cfg:
            logger.error(f"No version config found in templates for PSD width {psd.width}")
            return None

        # 1. DISCOVERY Mode: Collect ALL type layers even if hidden
        type_pool = []
        for l in psd.descendants():
            if l.kind == 'type':
                type_pool.append({
                    "name": l.name.upper(),
                    "text": l.text.strip().upper(),
                    "bbox": l.bbox,
                    "layer": l
                })
        
        # Sort by position (X then Y) to handle duplicate text consistently
        type_pool.sort(key=lambda x: (x["bbox"][0], x["bbox"][1]))
        
        # Identity-Field to Coordinate Mapping
        active_replacement_map = {}
        layer_map = version_cfg.get("layer_map", {})
        
        for field, m_cfg in layer_map.items():
            placeholder = m_cfg["placeholder"].upper()
            index = m_cfg.get("index", 0)
            
            # Find matching instances in pool
            matches = [t for t in type_pool if t["name"] == placeholder or t["text"] == placeholder]
            if matches and index < len(matches):
                target = matches[index]
                active_replacement_map[field] = {
                    "pos": (target["bbox"][0], target["bbox"][1]),
                    "size": target["bbox"][3] - target["bbox"][1] # height
                }
                logger.debug(f"Matched field '{field}' to layer text '{placeholder}' (index {index}) at {target['bbox'][0]},{target['bbox'][1]}")

        # 2. Composite BASE (BG only)
        # Hide almost everything for the clean composite
        for layer in psd.descendants():
            if layer.kind in ['type', 'pixel', 'smartobject'] and 'BG' not in layer.name.upper():
                layer.visible = False
        
        img = psd.composite()
        draw = ImageDraw.Draw(img)

        # 3. Enhanced Rendering Loop (Photos, Sigs, Text)
        self._fill_enhanced(img, draw, identity, template_psd.parent, version_cfg, active_replacement_map)
        
        # 4. Re-apply Top-level PSD Overlays (Holograms, Seal)
        # We find layers that should be ON TOP of everything (like the seal)
        top_layers = []
        for layer in psd.descendants():
             # Layers often used as overlays/holograms
             if any(kw in layer.name.upper() for kw in ['HOLO', 'SEAL', 'VICROADS', 'STAMP', 'CREST']):
                 if layer.kind == 'pixel' and 'SIGN' not in layer.name.upper():
                     top_layers.append(layer)
        
        for t_layer in top_layers:
            try:
                # Composite the single layer and paste as overlay
                # We use opacity from PSD
                overlay = t_layer.composite()
                img.paste(overlay, (t_layer.left, t_layer.top), overlay)
                logger.info(f"Re-applied overlay layer: {t_layer.name}")
            except Exception as e:
                logger.warning(f"Failed to re-apply overlay {t_layer.name}: {e}")

        # 5. Global Card texture (Make it look real)
        img = self._apply_card_texture(img)

        # 6. Place card over random scene background
        img = self._apply_bg(img, psd.width, psd.height)

        # 7. Save
        output_name = f"DL_{identity.get('last_name', 'Anon')}_{country_code}.png"
        output_path = self.output_dir / output_name
        img.save(output_path, "PNG")
        logger.info(f"Generated: {output_path}")
        return str(output_path)

    def create_license_back(self, identity: Dict[str, Any]) -> Optional[str]:
        """Generate the back side of an Australian driving licence."""
        country_code = identity.get("country", "AU").upper()
        country_config = None
        resolved_code = country_code
        for key, data in self.config.items():
            if country_code == key or country_code in data.get("alias", []):
                country_config = data
                resolved_code = key
                break
        if not country_config:
            logger.error(f"No config found for country: {country_code}")
            return None

        back_versions = country_config.get("back_versions")
        if not back_versions:
            logger.error(f"No back_versions config for country: {country_code}")
            return None

        template_psd = self._get_template_path(resolved_code, side="BACK")
        if not template_psd:
            logger.error(f"No BACK template PSD found for: {country_code}")
            return None

        logger.info(f"Rendering back side from: {template_psd.name}")
        psd = PSDImage.open(template_psd)

        # Select version by PSD width
        version_cfg = None
        for vname, vdata in back_versions.items():
            if vdata.get("min_width", 0) <= psd.width <= vdata.get("max_width", 99999):
                version_cfg = vdata
                break
        if not version_cfg:
            logger.error(f"No back version config matched PSD width {psd.width}")
            return None

        # DISCOVERY: collect ALL type layers (visible or not), sorted left-to-right
        type_pool = []
        for l in psd.descendants():
            if l.kind == "type":
                type_pool.append({
                    "name": l.name.upper(),
                    "text": l.text.strip().upper(),
                    "bbox": l.bbox,
                    "layer": l,
                })
        type_pool.sort(key=lambda x: (x["bbox"][0], x["bbox"][1]))

        active_replacement_map = {}
        layers_to_hide = []          # only the placeholder layers we are replacing
        layer_map = version_cfg.get("layer_map", {})
        for field, m_cfg in layer_map.items():
            placeholder = m_cfg["placeholder"].upper()
            index = m_cfg.get("index", 0)
            matches = [t for t in type_pool if t["name"] == placeholder or t["text"] == placeholder]
            if matches and index < len(matches):
                target = matches[index]
                active_replacement_map[field] = {
                    "pos": (target["bbox"][0], target["bbox"][1]),
                    "size": target["bbox"][3] - target["bbox"][1],
                    "layer": target["layer"],
                }
                layers_to_hide.append(target["layer"])
                logger.debug(f"[BACK] Matched '{field}' -> '{placeholder}' idx={index} at {target['bbox'][0]},{target['bbox'][1]}")

        # Hide ONLY the placeholder layers we intend to replace.
        # All other layers (static labels, conditions text, card artwork) stay visible
        # so the full authentic background composites correctly.
        for layer in layers_to_hide:
            layer.visible = False

        img = psd.composite()
        draw = ImageDraw.Draw(img)

        # Draw discovered text fields
        folder = template_psd.parent
        for field, data in active_replacement_map.items():
            p_pos = data["pos"]
            p_size = data["size"]

            f_cfg = version_cfg.get("fields", {}).get(field, {})
            text = self._format_field(field, f_cfg, identity)
            if not text:
                continue

            final_font_size = int(p_size * 0.9)
            font_key = f_cfg.get("font", "main")
            font_info = version_cfg["fonts"].get(font_key, version_cfg["fonts"]["main"])
            font = self._get_font(folder, font_info["name"], final_font_size)

            fill_raw = f_cfg.get("fill", (20, 20, 20, 255))
            fill = tuple(fill_raw) if isinstance(fill_raw, list) else fill_raw

            draw.text((p_pos[0], p_pos[1]), text, font=font, fill=fill)
            logger.debug(f"[BACK] Drew '{field}': '{text}' at {p_pos}")

        # Fallback: static-position fields defined with "pos" key
        for field, f_cfg in version_cfg.get("fields", {}).items():
            if field in active_replacement_map or "pos" not in f_cfg:
                continue
            text = self._format_field(field, f_cfg, identity)
            if not text:
                continue
            font = self._get_font(folder, version_cfg["fonts"]["main"]["name"], version_cfg["fonts"]["main"]["size"])
            draw.text(tuple(f_cfg["pos"]), text, font=font, fill=f_cfg.get("fill", "black"))

        # Global card texture
        img = self._apply_card_texture(img)

        # Place card over random scene background
        img = self._apply_bg(img, psd.width, psd.height)

        output_name = f"DL_{identity.get('last_name', 'Anon')}_{country_code}_BACK.png"
        output_path = self.output_dir / output_name
        img.save(output_path, "PNG")
        logger.info(f"Generated back: {output_path}")
        return str(output_path)

    def _fill_enhanced(self, img: Image.Image, draw: ImageDraw.Draw, identity: Dict, folder: Path, cfg: Dict, discovered: Dict):
        print(f"DEBUG: Starting _fill_enhanced for {identity.get('last_name')}")
        """Replacement logic with adaptive font sizing and color matching."""
        
        # 1. Assets (Draw FIRST so text overlays them like in real licenses)
        for atype in ["photo", "signature"]:
            a_cfg = cfg.get(atype)
            if not a_cfg: continue
            pos = tuple(a_cfg["pos"])
            if atype == "photo":
                path = identity.get("photo_path")
                if not path or not os.path.exists(path):
                    path = self._get_random_photo()
                    if path:
                        logger.info(f"Using random photo: {Path(path).name}")
                
                if path and os.path.exists(path):
                    country_code = identity.get("country", "GB").upper()
                    logger.info(f"Pasting photo from: {Path(path).name} at {pos}")
                    p_img = self._prepare_photo(path, *a_cfg["size"], country=country_code)
                    
                    # 1. Tone matching: slightly adjust to fit template
                    p_img = ImageEnhance.Color(p_img).enhance(0.9) # Subtle desaturation
                    p_img = ImageEnhance.Contrast(p_img).enhance(0.95) # Soften contrast
                    
                    img.paste(p_img, pos, p_img)

                    img.paste(p_img, pos, p_img)
                else:
                    logger.warning(f"No valid photo found for pasting!")
            else:
                name = f"{identity.get('first_name','')} {identity.get('last_name','')}"
                font_name = cfg["fonts"]["sig"]["name"]
                logger.info(f"Generating signature for '{name}' using {font_name}")
                s_img = self._generate_signature(name, folder, cfg["fonts"]["sig"], *a_cfg["size"])
                # Preserve transparency in signature paste
                img.paste(s_img, pos, s_img)

        # 2. Draw Discovered Fields
        for field, data in discovered.items():
            p_pos = data["pos"]
            p_size = data["size"]
            
            f_cfg = cfg.get("fields", {}).get(field, {})
            text = self._format_field(field, f_cfg, identity)
            if not text: continue
            
            # Adaptive font size based on PSD discovery height!
            final_font_size = int(p_size * 0.9) 
            font_info = cfg["fonts"].get(f_cfg.get("font", "main"))
            
            # Load Font with discovered size
            font = self._get_font(folder, font_info["name"], final_font_size)
            
            # Colors and Stroke
            fill_raw = f_cfg.get("fill", (20, 20, 20, 255))
            fill = tuple(fill_raw) if isinstance(fill_raw, list) else fill_raw
            sw = f_cfg.get("stroke_width", 0)
            sf_raw = f_cfg.get("stroke_fill", (0, 0, 0))
            sf = tuple(sf_raw) if isinstance(sf_raw, list) else sf_raw
            
            # Helper for tracking and multi-pass draw
            tracking = f_cfg.get("tracking", 0)
            def _draw(x, y, txt, f_obj, fill_clr, s_w=0, s_f=None):
                if tracking == 0:
                    draw.text((x, y), txt, font=f_obj, fill=fill_clr, stroke_width=s_w, stroke_fill=s_f)
                else:
                    cx, cy = x, y
                    for ch in txt:
                        draw.text((cx, cy), ch, font=f_obj, fill=fill_clr, stroke_width=s_w, stroke_fill=s_f)
                        cx += f_obj.getlength(ch) + tracking
            
            # Shadow
            if "shadow" in f_cfg:
                sx, sy = f_cfg["shadow"].get("offset", (2, 2))
                sfill_raw = f_cfg["shadow"].get("fill", (0, 0, 0, 200))
                sfill = tuple(sfill_raw) if isinstance(sfill_raw, list) else sfill_raw
                _draw(p_pos[0] + sx, p_pos[1] + sy, text, font, sfill)
            
            # Emboss effect (Metallic text)
            if f_cfg.get("emboss"):
                # Black outline
                for ox, oy in [(0, -1), (0, 1), (-1, 0), (1, 0)]:
                    _draw(p_pos[0] + ox, p_pos[1] + oy, text, font, (0, 0, 0, 200))
                # Top-left white highlight
                _draw(p_pos[0] - 1, p_pos[1] - 1, text, font, (255, 255, 255, 255))
            
            _draw(p_pos[0], p_pos[1], text, font, fill, sw, sf)

        # 3. Fallback for fields NOT discovered via layer map (e.g., photo/signature secondary text)
        for field, f_cfg in cfg.get("fields", {}).items():
            if field in discovered or "pos" not in f_cfg: continue
            text = self._format_field(field, f_cfg, identity)
            if not text: continue
            font = self._get_font(folder, cfg["fonts"]["main"]["name"], cfg["fonts"]["main"]["size"])
            draw.text(tuple(f_cfg["pos"]), text, font=font, fill=f_cfg.get("fill", "black"))

    def _format_field(self, name: str, info: Dict, identity: Dict) -> str:
        key = info.get("key", name)
        if "format" in info:
            return info["format"].format(
                day=identity.get("dob_day", "01"),
                month=identity.get("dob_month", "01"),
                year=identity.get("dob_year", "1990"),
                year_short=identity.get("dob_year", "1990")[-2:],
                first=identity.get("first_name", ""),
                last=identity.get("last_name", "")
            )
        if name == "license_num" and key not in identity:
            last = identity.get("last_name", "DOE")[:5].upper().ljust(5, '9')
            y2 = identity.get("dob_year", "1990")[-2:]; m = identity.get("dob_month", "01"); d = identity.get("dob_day", "01")
            return f"{last}{y2}{m}{d}X99XX"
        return str(identity.get(key, info.get("default", ""))).upper() if info.get("case","upper") == "upper" else str(identity.get(key, info.get("default", "")))

if __name__ == "__main__":
    factory = DLFactory()
    test_id = {
        "first_name": "JOHN", "last_name": "CITIZEN",
        "dob_day": "16", "dob_month": "03", "dob_year": "1984",
        "address": "77 SAMPLE PARADE", "city_state_zip": "KEW EAST VIC 3102",
        "license_num": "9876543", "country": "AU",
    }
    factory.create_license(test_id)
    factory.create_license_back(test_id)
