import sqlite3
import random
import os
from pathlib import Path
from faker import Faker
from loguru import logger
from difflib import get_close_matches

# 1. ROBUST PATH HANDLING (Finds DB relative to this file)
BASE_DIR = Path(__file__).parent.parent 
DB_PATH = BASE_DIR / "assets" / "identities.db"

class IdentityGenerator:
    def __init__(self):
        if not DB_PATH.exists():
            alt_path = Path("auto/assets/identities.db")
            if alt_path.exists():
                self.db_path = str(alt_path)
            else:
                logger.warning(f"⚠️ DB Missing at {DB_PATH}! Run db_importer.py first.")
                self.db_path = str(DB_PATH) 
        else:
            self.db_path = str(DB_PATH)
            
        self._fakers = {
            "DE": Faker("de_DE"), "IT": Faker("it_IT"), "ES": Faker("es_ES"),
            "NL": Faker("nl_NL"), "RO": Faker("ro_RO"), "PL": Faker("pl_PL"),
            "BE": Faker("nl_BE"), "UA": Faker("uk_UA"), "AU": Faker("en_AU"),
            "CA": Faker("en_CA"), "US": Faker("en_US")
        }

    def _get_date_format(self, country_code):
        if country_code in ["US", "CA"]: return "%m/%d/%Y"
        return "%d/%m/%Y"

    def _sanitize_zip(self, zipcode, country_code):
        if not zipcode: return ""
        zipcode = str(zipcode).strip()
        if country_code == "US" and "-" in zipcode:
            return zipcode.split("-")[0]
        return zipcode

    def _resolve_region(self, cursor, country_code, raw_region):
        if not raw_region: return None
        
        cursor.execute("SELECT DISTINCT admin_name1 FROM locations WHERE country_code = ?", (country_code,))
        all_names = [r[0] for r in cursor.fetchall() if r[0]]
        if raw_region in all_names: return raw_region
        
        matches = get_close_matches(raw_region, all_names, n=1, cutoff=0.6)
        if matches:
            logger.debug(f"📍 Fuzzy Region Map: '{raw_region}' -> '{matches[0]}'")
            return matches[0]

        cursor.execute("SELECT DISTINCT admin_code1 FROM locations WHERE country_code = ?", (country_code,))
        all_codes = [r[0] for r in cursor.fetchall() if r[0]]
        if raw_region in all_codes: return raw_region 

        return None

    def generate_identity(self, country_code: str, region_name: str = None):
        # Ensure country_code is safe string
        country_code = str(country_code).upper() if country_code else "US"
        fake = self._fakers.get(country_code, Faker("en_US"))
        
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # --- 1. PERSONAL INFO ---
                gender = random.choice(["male", "female"])
                first_name = fake.first_name_male() if gender == "male" else fake.first_name_female()
                last_name = fake.last_name()
                
                dob_date = fake.date_of_birth(minimum_age=21, maximum_age=58)
                
                dob_data = {
                    "day": str(dob_date.day),
                    "day_padded": f"{dob_date.day:02d}",
                    "month": str(dob_date.month),
                    "month_padded": f"{dob_date.month:02d}",
                    "month_name": dob_date.strftime("%B"),
                    "year": str(dob_date.year),
                    "year_short": str(dob_date.year)[-2:], 
                    "full_str": dob_date.strftime(self._get_date_format(country_code))
                }

                # --- 2. LOCATION ---
                city, zipcode, state = None, None, None
                loc_row = None
                
                resolved_region = self._resolve_region(cursor, country_code, region_name)
                
                if resolved_region:
                    col_to_match = "admin_code1" if len(resolved_region) <= 3 and country_code in ["US", "CA", "AU"] else "admin_name1"
                    query = f"SELECT place_name, postal_code, admin_name1 FROM locations WHERE country_code=? AND {col_to_match}=? ORDER BY RANDOM() LIMIT 1"
                    cursor.execute(query, (country_code, resolved_region))
                    loc_row = cursor.fetchone()

                if not loc_row:
                    if region_name: logger.warning(f"Region '{region_name}' empty/unknown in DB. Using National Random.")
                    query = "SELECT place_name, postal_code, admin_name1 FROM locations WHERE country_code=? ORDER BY RANDOM() LIMIT 1"
                    cursor.execute(query, (country_code,))
                    loc_row = cursor.fetchone()
                
                if loc_row:
                    city, zipcode, state = loc_row
                    city = str(city).strip()
                    state = str(state).strip()
                    zipcode = self._sanitize_zip(zipcode, country_code)
                else:
                    city, zipcode, state = fake.city(), fake.postcode(), (region_name or "Unknown")

                # --- 3. ADDRESS ---
                cursor.execute("SELECT street_name FROM streets WHERE country_code = ? ORDER BY RANDOM() LIMIT 1", (country_code,))
                street_row = cursor.fetchone()
                street_base = street_row[0] if street_row else fake.street_name()
                street_num = random.randint(1, 150)
                
                if country_code in ["US", "CA", "GB", "AU"]:
                    address = f"{street_num} {street_base}"
                else:
                    address = f"{street_base} {street_num}"

            return {
                "first_name": first_name,
                "last_name": last_name,
                "gender": gender,
                "dob_day": dob_data["day_padded"],
                "dob_month": dob_data["month_padded"],
                "dob_year": dob_data["year"],
                "dob_complex": dob_data,
                "country": country_code,
                "state": state,
                "city": city,
                "zip": zipcode,
                "address": address,
                "full_address": f"{address}, {city} {zipcode}"
            }
            
        except Exception as e:
            logger.exception(f"Identity Generation Critical Fail: {e}")
            
            # --- ROBUST FALLBACK (Safe Variable Scope) ---
            safe_country = country_code # We validated this at start of function
            dob_date = fake.date_of_birth(minimum_age=21, maximum_age=55)
            
            dob_data = {
                "day": str(dob_date.day),
                "day_padded": f"{dob_date.day:02d}",
                "month": str(dob_date.month),
                "month_padded": f"{dob_date.month:02d}",
                "month_name": dob_date.strftime("%B"),
                "year": str(dob_date.year),
                "year_short": str(dob_date.year)[-2:],
                "full_str": dob_date.strftime(self._get_date_format(safe_country))
            }
            
            fb_gender = random.choice(["male", "female"])
            fb_first_name = fake.first_name_male() if fb_gender == "male" else fake.first_name_female()
            
            # Use 'region_name' if passed, otherwise "Unknown"
            fb_state = region_name if region_name else "Unknown"
            
            return {
                "first_name": fb_first_name,
                "last_name": fake.last_name(),
                "gender": fb_gender,
                "dob_day": dob_data["day_padded"],
                "dob_month": dob_data["month_padded"],
                "dob_year": dob_data["year"],
                "dob_complex": dob_data,
                "country": safe_country,
                "state": fb_state, 
                "city": fake.city(),
                "zip": fake.postcode(),
                "address": fake.street_address(),
                "full_address": f"{fake.street_address()}, {fake.city()} {fake.postcode()}"
            }
