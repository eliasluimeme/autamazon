try:
    import pyotp
    PYOTP_AVAILABLE = True
except ImportError:
    PYOTP_AVAILABLE = False

from loguru import logger

def generate_totp_code(secret_key: str) -> str | None:
    """
    Generates a 6-digit TOTP code from a Base32 secret key.
    Replaces the requirement to use 2fa.zone via browser.
    """
    if not PYOTP_AVAILABLE:
        logger.error("pyotp is not installed. Run 'pip install pyotp'.")
        return None
        
    try:
        # Clean secret (remove spaces)
        clean_secret = secret_key.replace(" ", "").strip()
        totp = pyotp.TOTP(clean_secret)
        code = totp.now()
        logger.info(f"✅ Generated TOTP code locally: {code}")
        return code
    except Exception as e:
        logger.error(f"Failed to generate TOTP: {e}")
        return None
