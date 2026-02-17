import uuid
import random
from modules.config import (
    DECODO_PROXY_HOST,
    DECODO_PROXY_PORT,
    DECODO_USERNAME,
    DECODO_PASSWORD,
    RANDOM_COUNTRY_MODE,
    TARGET_COUNTRY,
    PROXY_SESSION_DURATION
)

TOP_COUNTRIES = ["au", "it", "ca", "es", "de", "nl", "ro", "pl", "be", "ua"]

def get_proxy_config(country: str = None, city: str = None, session: bool = True) -> dict:
    """
    Generates a proxy configuration dictionary compatible with AdsPower.
    """
    if not (DECODO_USERNAME and DECODO_PASSWORD):
        print(f"DEBUG: Missing Creds. User={DECODO_USERNAME}")
        return None

    clean_username = DECODO_USERNAME.replace("user-", "")

    if RANDOM_COUNTRY_MODE:
        effective_country = random.choice(TOP_COUNTRIES)
    else:
        effective_country = country if country else TARGET_COUNTRY

    # Format: user-{username}-country-{country}[-city-{city}][-session-{sessionID}][-sessionduration-{minutes}]
    username_parts = [f"user-{clean_username}", f"country-{effective_country}"]
    
    if city:
        username_parts.append(f"city-{city}")
        
    if session:
        session_id = str(uuid.uuid4())[:8]
        username_parts.append(f"session-{session_id}")
        username_parts.append(f"sessionduration-{PROXY_SESSION_DURATION}")
        
    proxy_user = "-".join(username_parts)

    return {
        "proxy_soft": "other",
        "proxy_type": "http",
        "proxy_host": DECODO_PROXY_HOST,
        "proxy_port": DECODO_PROXY_PORT,
        "proxy_user": proxy_user,
        "proxy_password": DECODO_PASSWORD
    }
