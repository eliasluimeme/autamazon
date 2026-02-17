"""
Identity Generator for Outlook Signup

Generates user identities for Outlook account creation.
Uses the shared auto.modules.identity_generator if available,
otherwise implements local fallback.
"""

import sys
import os
import random
import string
from loguru import logger

# Try to import from shared auto.modules first
try:
    # Adjust path to include root
    sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../')))
    from modules.identity_generator import IdentityGenerator
    from modules.email_fabricator import EmailFabricator
    SHARED_MODULES_AVAILABLE = True
except ImportError:
    SHARED_MODULES_AVAILABLE = False
    logger.warning("Shared identity modules not found. Using local fallback.")

def generate_outlook_identity(country_code="US"):
    """
    Generates a full identity suitable for Outlook account creation.
    """
    outlook_identity = None
    
    if SHARED_MODULES_AVAILABLE:
        try:
            ig = IdentityGenerator()
            ef = EmailFabricator()
            
            # 1. Generate base identity
            identity = ig.generate_identity(country_code)
            
            # 2. Fabricate email handle
            full_email = ef.fabricate(identity, force_domain="outlook.com")
            email_handle = full_email.split("@")[0]
            
            outlook_identity = {
                "firstname": identity['first_name'],
                "lastname": identity['last_name'],
                "email_handle": email_handle,
                "password": generate_strong_password(),
                "dob_month": str(random.randint(1, 12)),
                "dob_day": str(random.randint(1, 28)),
                "dob_year": str(random.randint(1980, 2000)),
            }
            logger.info("Generated identity via shared modules")
            
        except Exception as e:
            logger.error(f"Failed to generate identity via shared modules: {e}")
            
    if not outlook_identity:
        # Fallback identity generation
        logger.info("Generating identity via fallback method")
        first_names = ["James", "John", "Robert", "Michael", "William", "David", "Richard", "Joseph", "Thomas", "Charles"]
        last_names = ["Smith", "Johnson", "Williams", "Jones", "Brown", "Davis", "Miller", "Wilson", "Moore", "Taylor"]
        
        fname = random.choice(first_names)
        lname = random.choice(last_names)
        handle = f"{fname.lower()}.{lname.lower()}{random.randint(100,9999)}"
        
        outlook_identity = {
            "firstname": fname,
            "lastname": lname,
            "email_handle": handle,
            "password": generate_strong_password(),
            "dob_month": str(random.randint(1, 12)),
            "dob_day": str(random.randint(1, 28)),
            "dob_year": str(random.randint(1980, 2000)),
        }

    # FINAL SANITIZATION: Ensure handle does not start with a digit (Amazon restriction)
    handle = outlook_identity["email_handle"]
    while handle and handle[0].isdigit():
        handle = handle[1:]
        
    if not handle or len(handle) < 3:
        # If too short or empty after stripping, prepend a prefix
        prefix = random.choice(string.ascii_lowercase)
        handle = f"{prefix}{handle}" if handle else f"{prefix}user{random.randint(100, 999)}"
        
    outlook_identity["email_handle"] = handle
    
    logger.info(f"👤 Final Generated Identity: {outlook_identity['firstname']} {outlook_identity['lastname']} ({handle})")
    return outlook_identity

def generate_strong_password(length=12):
    """Generates a password with upper, lower, digits and special chars"""
    chars = string.ascii_letters + string.digits + "!@#$%^&*"
    return "".join(random.choice(chars) for _ in range(length))
