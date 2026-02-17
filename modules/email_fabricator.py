import random
import re
import string
from datetime import datetime
from unidecode import unidecode
from loguru import logger

class EmailFabricator:
    def __init__(self, catchall_domains=None):
        self.catchall_domains = catchall_domains if catchall_domains else []
        
        # === 1. Domain Profiles (unchanged) ===
        self.domain_profiles = {
            "MODERN": ["gmail.com", "outlook.com", "icloud.com", "protonmail.com"],
            "LEGACY": ["yahoo.com", "hotmail.com", "aol.com", "live.com"],
            "DE": ["web.de", "gmx.de", "t-online.de", "freenet.de"],
            "UK": ["yahoo.co.uk", "btinternet.com", "virginmedia.com"],
            "IT": ["libero.it", "virgilio.it", "alice.it", "email.it"],
            "ES": ["terra.es", "yahoo.es", "hotmail.es"],
            "PL": ["onet.pl", "wp.pl", "interia.pl", "o2.pl"],
            "RO": ["yahoo.ro", "emag.ro"], 
            "NL": ["kpnmail.nl", "ziggo.nl"],
            "BE": ["proximus.be", "telenet.be"],
            "UA": ["ukr.net", "i.ua", "email.ua", "meta.ua"],
            "AU": ["bigpond.com", "optusnet.com.au"],
            "CA": ["rogers.com", "sympatico.ca", "shaw.ca"]
        }

        # === 2. Regional Markers (The "Local Pride" logic) ===
        # Users often add city/area codes to handles
        self.geo_markers = {
            "US": ["nyc", "la", "cali", "usa", "ny", "tx"],
            "DE": ["berlin", "hh", "munich", "de", "ger"],
            "UK": ["ldn", "uk", "london", "gb"],
            "FR": ["paris", "75", "13", "69", "fr"], # Dept numbers are HUGE in France
            "IT": ["roma", "milano", "ita", "napoli"],
            "PL": ["pl", "waw", "pol", "polska"],
            "CA": ["to", "yyz", "van", "bc", "ca"],
            "AU": ["oz", "aus", "syd", "melb"]
        }

        self.abstract_concepts = {
            "NATURE": ["sky", "storm", "river", "ocean", "mountain", "forest", "moon", "sun", "fire", "ice"],
            "ANIMALS": ["wolf", "fox", "bear", "eagle", "hawk", "tiger", "lion", "panda", "shark", "viper", "cobra"],
            "COLORS": ["blue", "red", "black", "silver", "gold", "neon", "dark", "white", "green"],
            "GAMER": ["lucky", "win", "play", "bet", "pro", "vip", "king", "boss", "777", "88", "crypto", "god", "master"],
            "SPORTS": ["kicker", "striker", "goal", "fit", "gym", "run", "rider", "driver", "champ"],
            "LUXURY": ["rich", "cash", "gold", "diamond", "prime", "elite", "boss", "ceo"]
        }
        
        self.keyboard_walks = ["qwe", "wer", "asd", "zxc", "123", "1234", "qaz", "wsx", "007", "000"]
        self.leet_map = {'a': '4', 'e': '3', 'i': '1', 'o': '0', 's': '5', 't': '7', 'b': '8'}

    def _sanitize_name(self, name):
        if not name: return "user"
        name = name.lower()
        name = name.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
        clean = unidecode(name)
        return "".join(c for c in clean if c.isalnum())

    def _apply_leet(self, text, intensity=0.5):
        if random.random() > intensity: return text
        chars = list(text)
        for i, char in enumerate(chars):
            if char in self.leet_map and random.random() < 0.5:
                chars[i] = self.leet_map[char]
        return "".join(chars)

    def _remove_vowels(self, text):
        """
        Stylistic choice often used by younger gens (e.g., 'brandon' -> 'brndn')
        """
        # Only do this if name is long enough
        if len(text) < 5: return text
        vowels = "aeiou"
        # Keep first letter always
        first = text[0]
        rest = "".join([c for c in text[1:] if c not in vowels])
        return first + rest

    def _get_zodiac_sign(self, day, month):
        day, month = int(day), int(month)
        if (month == 1 and day >= 20) or (month == 2 and day <= 18): return "aquarius"
        if (month == 2 and day >= 19) or (month == 3 and day <= 20): return "pisces"
        if (month == 3 and day >= 21) or (month == 4 and day <= 19): return "aries"
        if (month == 4 and day >= 20) or (month == 5 and day <= 20): return "taurus"
        if (month == 5 and day >= 21) or (month == 6 and day <= 20): return "gemini"
        if (month == 6 and day >= 21) or (month == 7 and day <= 22): return "cancer"
        if (month == 7 and day >= 23) or (month == 8 and day <= 22): return "leo"
        if (month == 8 and day >= 23) or (month == 9 and day <= 22): return "virgo"
        if (month == 9 and day >= 23) or (month == 10 and day <= 22): return "libra"
        if (month == 10 and day >= 23) or (month == 11 and day <= 21): return "scorpio"
        if (month == 11 and day >= 22) or (month == 12 and day <= 21): return "sagittarius"
        return "capricorn"

    def fabricate(self, identity, force_domain=None):
        raw_fname = self._sanitize_name(identity['first_name'])
        raw_lname = self._sanitize_name(identity['last_name'])
        country = identity.get('country', 'GLOBAL')
        
        # === 1. AGE CONTEXT ===
        current_year = datetime.now().year
        birth_year = int(identity['dob_complex']['year'])
        age = current_year - birth_year
        
        is_boomer = age > 45
        is_zoomer = age < 30
        
        # === 2. DATA EXTRACTION ===
        year_short = identity['dob_complex']['year_short']
        day = identity['dob_complex']['day']
        zip_frag = identity['zip'][:3] if identity.get('zip') and len(identity['zip']) >= 3 else "123"
        zodiac = self._get_zodiac_sign(day, identity['dob_complex']['month'])

        patterns = []
        
        # === 3. PATTERN LOGIC ===
        
        if is_boomer:
            # Older: Simple, structured, often with full year
            sep = random.choice([".", "", ""])
            patterns.extend([
                f"{raw_fname}{sep}{raw_lname}",
                f"{raw_fname}{sep}{raw_lname}{birth_year}",
                f"{raw_lname}{sep}{raw_fname}{year_short}",
                f"{raw_fname[0]}{raw_lname}{birth_year}"
            ])
        else:
            # Younger: Varied, chaotic, stylistic
            fnames = [raw_fname]
            if len(raw_fname) > 4: fnames.extend([raw_fname[:3], raw_fname[:4]])
            if raw_fname.endswith("ie"): fnames.append(raw_fname[:-1])
            
            # Apply Vowel Removal (Stylistic choice - 15% chance)
            if random.random() < 0.15:
                fnames.append(self._remove_vowels(raw_fname)) # 'alexander' -> 'alxndr'
                
            fname = random.choice(fnames)
            sep = random.choice([".", "_", "_", ""])
            
            # Standard
            patterns.extend([
                f"{fname}{sep}{raw_lname}",
                f"{fname}{sep}{raw_lname}{year_short}",
                f"{fname}{year_short}{zip_frag}",
            ])
            
            # Astrology
            patterns.append(f"{fname}.{zodiac}{year_short}")
            
            # Geo-Marker Injection (e.g. 'alex.nyc')
            if country in self.geo_markers and random.random() < 0.25:
                geo = random.choice(self.geo_markers[country])
                patterns.append(f"{fname}{sep}{raw_lname}.{geo}")
                patterns.append(f"{fname}_{geo}_{year_short}")

            # Google "Auto-Suggestion" Simulation (The "Taken" effect)
            # e.g., name + random 4 digits (Very common gmail pattern)
            auto_digits = random.randint(1000, 9999)
            patterns.append(f"{raw_fname}.{raw_lname}{auto_digits}")
            patterns.append(f"{raw_fname}{raw_lname}{auto_digits}")

        # === 4. ABSTRACT HANDLE (30% Chance) ===
        if not is_boomer and random.random() < 0.30:
            cat = random.choice(list(self.abstract_concepts.keys()))
            word = random.choice(self.abstract_concepts[cat])
            suffix = random.choice([str(birth_year), year_short, zip_frag, "88", "777", day, "x", "xx"])
            
            abstract_patterns = [
                f"{word}.{raw_fname}{year_short}",
                f"{word}_{suffix}",
                f"its.{word}{year_short}", # its.wolf90
                f"{raw_fname}.{word}"
            ]
            handle = random.choice(abstract_patterns)
        else:
            handle = random.choice(patterns)

        # === 5. CHAOS MODIFIERS ===
        if is_zoomer:
            handle = self._apply_leet(handle, intensity=0.25)

        handle = re.sub(r'[\._]{2,}', '.', handle).strip("._")
        
        # Smart Truncation
        if len(handle) > 30:
            handle = f"{handle[:25]}{random.randint(10,99)}"
        if len(handle) < 6:
            handle += str(birth_year)

        # === 6. DOMAIN SELECTION ===
        if force_domain:
            domain = force_domain
        elif self.catchall_domains:
            domain = random.choice(self.catchall_domains)
        else:
            if country in self.public_domains and random.random() < 0.4:
                domain = random.choice(self.public_domains[country])
            else:
                profile = "LEGACY" if is_boomer else "MODERN"
                # 10% crossover chance
                if random.random() < 0.1: profile = "MODERN" if is_boomer else "LEGACY"
                domain = random.choice(self.domain_profiles[profile])

        return f"{handle}@{domain}".lower()
