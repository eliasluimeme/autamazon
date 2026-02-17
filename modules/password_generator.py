import random
import string
import re
from unidecode import unidecode
from loguru import logger

class PasswordGenerator:
    def __init__(self):
        # === 1. SYMBOLS ===
        # Humans prefer "easy" symbols on the keyboard (Shift+1,2,3...)
        self.common_symbols = ["!", "@", "#", "$", "*", "_", "-", "."]
        
        # === 2. WORD BANKS ===
        self.word_banks = {
            "PETS": ["Luna", "Bella", "Max", "Charlie", "Coco", "Buddy", "Rocky", "Milo", "Daisy", "Simba"],
            "MONEY": ["Cash", "Rich", "Gold", "Dollar", "Euro", "Million", "Billion", "Lucky", "Win", "Bonus"],
            "POWER": ["Dragon", "Tiger", "Lion", "Eagle", "King", "Queen", "Boss", "Master", "Ninja", "Viper"],
            "VIBE": ["Happy", "Smile", "Summer", "Winter", "Ocean", "Sunset", "Love", "Dream", "Star", "Moon"],
            "SPORTS": ["Soccer", "Football", "Basket", "Goal", "Champ", "Striker", "Kicker", "Gym", "Fit"],
            "VERBS": ["Open", "Login", "Access", "Unlock", "Start", "Go", "Make", "Take"]
        }

        # === 3. KEYBOARD WALKS ===
        self.keyboard_walks = ["Qwert", "Qwerty", "Asdf", "Zxcv", "12345", "Qazwsx"]

        # === 4. SUBSTITUTION MAP (For inner injection) ===
        self.substitutions = {
            'a': '@', 's': '$', 'i': '!', 'l': '!', 'o': '0', 'e': '3', 't': '7'
        }

    def _sanitize(self, text):
        if not text: return ""
        return unidecode(str(text)).replace(" ", "").strip()

    def _smart_inject_special(self, text):
        """
        Intelligently adds a special character based on human patterns.
        Does NOT just append to end.
        """
        symbol = random.choice(self.common_symbols)
        strategy = random.random()

        # Strategy 1: Substitution (e.g. "Dragon" -> "Dr@gon") - 30%
        # Looks for substitutable chars first.
        candidates = [i for i, char in enumerate(text.lower()) if char in self.substitutions]
        if candidates and strategy < 0.30:
            idx = random.choice(candidates)
            char = text[idx].lower()
            # Replace char with symbol equivalent
            new_text = text[:idx] + self.substitutions[char] + text[idx+1:]
            return new_text

        # Strategy 2: Separator (e.g. "BlueDragon" -> "Blue_Dragon") - 30%
        # Finds the boundary between CamelCase words or Words and Numbers
        # Regex finds change from Lower to Upper OR Alpha to Digit
        boundaries = [m.start() for m in re.finditer(r'(?<=[a-z])(?=[A-Z])|(?<=[a-zA-Z])(?=[0-9])', text)]
        if boundaries and strategy < 0.60:
            idx = random.choice(boundaries)
            # Insert symbol (usually . or _ or @)
            sep = random.choice([".", "_", "@", "#"])
            return text[:idx] + sep + text[idx:]

        # Strategy 3: Prefix (e.g. "!Password") - 10%
        if strategy < 0.70:
            return symbol + text

        # Strategy 4: Suffix (e.g. "Password!") - 30% (Classic)
        return text + symbol

    def _enforce_complexity(self, password):
        """
        Ensures password meets strict Casino requirements (8 chars, 1 upper, 1 lower, 1 digit, 1 symbol)
        without making it look generated.
        """
        # 1. Length Fix
        while len(password) < 8:
            password += str(random.randint(0, 9))

        # 2. Check Missing Types
        missing = []
        if not any(c.isupper() for c in password): missing.append("upper")
        if not any(c.islower() for c in password): missing.append("lower")
        if not any(c.isdigit() for c in password): missing.append("digit")
        if not any(c in string.punctuation for c in password): missing.append("symbol")

        if not missing:
            return password

        # 3. Random Insertion (Fixing the "Append Only" bug)
        # We convert to list to mutate
        p_list = list(password)
        
        for m in missing:
            # Pick a random spot to INSERT (don't overwrite if possible to keep readability)
            idx = random.randint(0, len(p_list))
            
            if m == "upper":
                # Try to capitalize an existing letter first
                letter_indices = [i for i, c in enumerate(p_list) if c.isalpha()]
                if letter_indices:
                    idx = random.choice(letter_indices)
                    p_list[idx] = p_list[idx].upper()
                else:
                    p_list.insert(idx, random.choice(string.ascii_uppercase))
                    
            elif m == "lower":
                p_list.insert(idx, random.choice(string.ascii_lowercase))
                
            elif m == "digit":
                # Humans usually put digits at end or middle
                if random.random() > 0.5:
                    p_list.append(str(random.randint(0, 9)))
                else:
                    p_list.insert(idx, str(random.randint(0, 9)))
                    
            elif m == "symbol":
                # Use smart injection logic if possible, otherwise insert random
                sym = random.choice(self.common_symbols)
                p_list.insert(idx, sym)

        return "".join(p_list)

    def generate(self, identity=None, email_handle=None):
        roll = random.random()
        
        # === STRATEGY A: CONCEPT + NUMBER (40%) ===
        # e.g. "Blue_Eagle99", "Lucky#777"
        if roll < 0.40:
            category = random.choice(list(self.word_banks.keys()))
            word = random.choice(self.word_banks[category])
            
            # 50% chance to be Lowercase vs Capitalized
            if random.random() < 0.3: word = word.lower()
            
            # Number source
            if identity:
                num = random.choice([
                    identity['dob_complex']['year'],
                    identity['dob_complex']['year_short'],
                    identity['zip'][:3] if len(identity['zip']) > 2 else "123"
                ])
            else:
                num = str(random.randint(20, 99))

            raw_pass = f"{word}{num}"

        # === STRATEGY B: IDENTITY BASED (30%) ===
        # e.g. "Alex.Smith!", "Berlin1990"
        elif roll < 0.70 and identity:
            fname = self._sanitize(identity['first_name']).capitalize()
            lname = self._sanitize(identity['last_name']).capitalize()
            city = self._sanitize(identity['city']).capitalize()
            # Handle potential missing or malformed dob data gracefully
            if 'dob_complex' in identity and 'year' in identity['dob_complex']:
                year = identity['dob_complex']['year']
            else:
                 year = str(random.randint(1970, 2005))
            
            # Randomized ordering
            if random.random() < 0.5:
                raw_pass = f"{fname}{lname}{year}"
            else:
                raw_pass = f"{city}{lname}{random.randint(1,99)}"
                
            # If email handle exists, use it (High Trust)
            if email_handle and random.random() < 0.4:
                # Strip non-alphanumeric for base
                clean_handle = re.sub(r'[^a-zA-Z0-9]', '', email_handle)
                # Capitalize first letter (Human habit)
                raw_pass = clean_handle.capitalize()

        # === STRATEGY C: PHRASES (20%) ===
        # e.g. "ILoveSummer", "GoLakers24"
        elif roll < 0.90:
            verb = random.choice(self.word_banks["VERBS"])
            noun = random.choice(self.word_banks["PETS"] + self.word_banks["VIBE"])
            num = random.randint(1, 99)
            raw_pass = f"{verb}{noun}{num}"

        # === STRATEGY D: LAZY PATTERNS (10%) ===
        # e.g. "Qwert12345"
        else:
            walk = random.choice(self.keyboard_walks)
            start = random.choice(["Pass", "My", "Go", "User"])
            raw_pass = f"{start}{walk}"

        # === 1. SMART SYMBOL INJECTION ===
        # Instead of just appending '!', we try to substitute or insert
        # Only if strict symbol req not met yet
        if not any(c in string.punctuation for c in raw_pass):
            raw_pass = self._smart_inject_special(raw_pass)

        # === 2. FINAL COMPLEXITY CHECK ===
        # This will randomly insert characters anywhere in string if missing requirements
        final_pass = self._enforce_complexity(raw_pass)
        
        return final_pass
