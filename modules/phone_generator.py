import random
import phonenumbers
from phonenumbers import carrier, number_type, PhoneNumberType
from loguru import logger

class PhoneGenerator:
    def __init__(self):
        # === A. INTERNATIONAL MOBILE PREFIXES (Non-Geographic) ===
        # These countries use specific prefixes for mobile phones. 
        # They do NOT depend on the city/state of the proxy.
        self.mobile_prefixes = {
            "DE": ["151", "160", "170", "171", "175", "152", "172", "173", "174", "157", "163", "177", "178", "159", "176", "179"], 
            "IT": ["320", "328", "329", "330", "333", "334", "335", "336", "337", "338", "339", "340", "347", "348", "349", "350", "351", "360", "366", "368", "370", "377", "380", "388", "389", "390", "391", "392", "393", "351", "371", "375"], 
            "ES": ["60", "61", "62", "63", "64", "65", "66", "67", "68", "69", "71", "72", "73", "74"], 
            "NL": ["61", "62", "63", "64", "65", "68", "69"], 
            "RO": ["72", "73", "74", "75", "76", "77", "78"], 
            "PL": ["50", "51", "53", "57", "60", "66", "69", "72", "73", "78", "79", "88", "45"], 
            "BE": ["455", "456", "460", "465", "466", "467", "468", "470", "471", "472", "473", "474", "475", "476", "477", "478", "479", "480", "483", "484", "485", "486", "487", "488", "489", "490", "491", "492", "493", "494", "495", "496", "497", "498", "499"], 
            "UA": ["50", "66", "95", "99", "67", "68", "96", "97", "98", "63", "73", "93", "91", "92", "94"], 
            "AU": ["4"], 
        }

        # === B. NORTH AMERICAN NUMBERING PLAN (Geo-Specific) ===
        # Full coverage of US States and CA Provinces.
        self.nanp_mapping = {
            # --- CANADA (CA) ---
            "CA": {
                "ON": ["416", "647", "437", "905", "289", "365", "519", "226", "548", "613", "343", "705", "249", "807"], # Ontario
                "QC": ["514", "438", "263", "450", "579", "354", "819", "873", "468", "418", "581", "367"], # Quebec
                "BC": ["604", "778", "236", "672", "250"], # British Columbia
                "AB": ["403", "587", "825", "368", "780"], # Alberta
                "MB": ["204", "431", "584"], # Manitoba
                "SK": ["306", "639", "474"], # Saskatchewan
                "NS": ["902", "782"], # Nova Scotia (Shared with PEI)
                "NB": ["506"], # New Brunswick
                "NL": ["709"], # Newfoundland & Labrador
                "PE": ["902", "782"], # Prince Edward Island
                "NT": ["867"], "NU": ["867"], "YT": ["867"] # Territories
            },
            # --- UNITED STATES (US) ---
            "US": {
                "AL": ["205", "251", "256", "334", "938"],
                "AK": ["907"],
                "AZ": ["480", "520", "602", "623", "928"],
                "AR": ["479", "501", "870"],
                "CA": ["209", "213", "310", "323", "408", "415", "510", "530", "559", "562", "619", "626", "650", "661", "707", "714", "760", "805", "818", "831", "858", "909", "916", "925", "949", "951"],
                "CO": ["303", "719", "970", "720"],
                "CT": ["203", "475", "860", "959"],
                "DE": ["302"],
                "FL": ["239", "305", "321", "352", "386", "407", "561", "727", "754", "772", "786", "813", "850", "863", "904", "941", "954"],
                "GA": ["229", "404", "470", "478", "678", "706", "762", "770", "912"],
                "HI": ["808"],
                "ID": ["208", "986"],
                "IL": ["217", "224", "309", "312", "331", "618", "630", "708", "773", "815", "847", "872"],
                "IN": ["219", "260", "317", "463", "574", "765", "812", "930"],
                "IA": ["319", "515", "563", "641", "712"],
                "KS": ["316", "620", "785", "913"],
                "KY": ["270", "364", "502", "606", "859"],
                "LA": ["225", "318", "337", "504", "985"],
                "ME": ["207"],
                "MD": ["240", "301", "410", "443", "667"],
                "MA": ["339", "351", "413", "508", "617", "774", "781", "857", "978"],
                "MI": ["231", "248", "269", "313", "517", "586", "616", "734", "810", "906", "947", "989"],
                "MN": ["218", "320", "507", "612", "651", "763", "952"],
                "MS": ["228", "601", "662", "769"],
                "MO": ["314", "417", "573", "636", "660", "816"],
                "MT": ["406"],
                "NE": ["308", "402", "531"],
                "NV": ["702", "725", "775"],
                "NH": ["603"],
                "NJ": ["201", "551", "609", "732", "848", "856", "862", "908", "973"],
                "NM": ["505", "575"],
                "NY": ["212", "315", "332", "347", "516", "518", "585", "607", "631", "646", "680", "716", "718", "838", "845", "914", "917", "929", "934"],
                "NC": ["252", "336", "704", "743", "828", "910", "919", "980", "984"],
                "ND": ["701"],
                "OH": ["216", "234", "330", "419", "440", "513", "567", "614", "740", "937"],
                "OK": ["405", "539", "580", "918"],
                "OR": ["458", "503", "541", "971"],
                "PA": ["215", "267", "272", "412", "484", "570", "610", "717", "724", "814", "878"],
                "RI": ["401"],
                "SC": ["803", "843", "864"],
                "SD": ["605"],
                "TN": ["423", "615", "629", "731", "865", "901", "931"],
                "TX": ["210", "214", "254", "281", "325", "346", "361", "409", "432", "469", "512", "682", "713", "737", "806", "817", "830", "832", "903", "915", "936", "940", "956", "972", "979"],
                "UT": ["385", "435", "801"],
                "VT": ["802"],
                "VA": ["276", "434", "540", "571", "703", "757", "804"],
                "WA": ["206", "253", "360", "425", "509", "564"],
                "WV": ["304", "681"],
                "WI": ["262", "414", "534", "608", "715", "920"],
                "WY": ["307"],
                "DC": ["202"]
            }
        }

    def generate(self, country_code, region_code=None, output_format="E164"):
        country_code = country_code.upper()
        
        # Retry logic ensures valid libphonenumber parsing
        for _ in range(30):
            try:
                raw_number = self._craft_raw_number(country_code, region_code)
                parsed_num = phonenumbers.parse(raw_number, country_code)
                
                if not phonenumbers.is_valid_number(parsed_num):
                    continue
                
                # Critical Check: Must be Mobile or Fixed/Mobile (NANP)
                num_type = number_type(parsed_num)
                if num_type not in [PhoneNumberType.MOBILE, PhoneNumberType.FIXED_LINE_OR_MOBILE]:
                    continue

                # Formatting output
                formatted = phonenumbers.format_number(parsed_num, phonenumbers.PhoneNumberFormat.E164)
                
                if output_format == "E164": return formatted
                if output_format == "NATIONAL": return phonenumbers.format_number(parsed_num, phonenumbers.PhoneNumberFormat.NATIONAL)
                if output_format == "RAW": return formatted.replace("+", "")
                if output_format == "RAW_NO_ZERO": return phonenumbers.national_significant_number(parsed_num)
                
                return formatted

            except Exception:
                continue
        
        # Fallback if generation fails
        logger.error(f"Failed to generate valid number for {country_code} {region_code}")
        return None

    def _craft_raw_number(self, country_code, region_code):
        # NANP Logic (US/CA)
        if country_code in ["US", "CA"]:
            default_regions = {"US": "NY", "CA": "ON"}
            
            # Smart Fallback for Region
            if not region_code or region_code not in self.nanp_mapping[country_code]:
                region_code = default_regions[country_code]
                
            codes = self.nanp_mapping[country_code][region_code]
            area = random.choice(codes)
            exchange = random.randint(200, 999)
            subscriber = random.randint(1000, 9999)
            return f"{area}{exchange}{subscriber}"

        # International Logic
        if country_code in self.mobile_prefixes:
            prefix = random.choice(self.mobile_prefixes[country_code])
            
            # Tail Lengths based on country rules
            if country_code == "DE":
                tail_len = random.choice([7, 8])
            elif country_code == "AU":
                tail_len = 8
            elif country_code in ["PL", "ES", "RO", "UA"]:
                tail_len = 7
            elif country_code == "NL":
                # NL NSN is 9 digits. Prefix is usually 2 digits (e.g. 61).
                tail_len = 9 - len(str(prefix))
            elif country_code == "BE":
                tail_len = 6
            elif country_code == "IT":
                tail_len = random.choice([6, 7])
            else:
                tail_len = 7
                
            tail = ''.join([str(random.randint(0, 9)) for _ in range(tail_len)])
            
            # Special formatting for Australia inputs
            if country_code == "AU":
                return f"0{prefix}{tail}"
                
            return f"{prefix}{tail}"

        raise ValueError(f"Country {country_code} not configured")
