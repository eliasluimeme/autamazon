from loguru import logger
import random

# Import your modules
from modules.identity_generator import IdentityGenerator
from modules.phone_generator import PhoneGenerator
from modules.email_fabricator import EmailFabricator
from modules.password_generator import PasswordGenerator

class PersonaFactory:
    def __init__(self, catchall_domains=None):
        self.id_gen = IdentityGenerator()
        self.phone_gen = PhoneGenerator()
        self.email_gen = EmailFabricator(catchall_domains=catchall_domains)
        self.pass_gen = PasswordGenerator()

    def create_persona(self, country_code, region_name=None):
        """
        Creates a fully cohesive identity where all data points align.
        """
        logger.info(f"🏗️ Constructing Persona for {country_code} ({region_name or 'Random'})...")
        
        # 1. Base Identity (Name, Address, DOB, Geo)
        identity = self.id_gen.generate_identity(country_code, region_name)
        
        # 2. Phone Number (Geo-Consistent)
        # We pass the resolved region from identity to ensure phone area code matches city
        phone = self.phone_gen.generate(
            identity['country'], 
            region_code=identity.get('state'), # The code generated "state" which maps to region
            output_format="E164"
        )
        
        # 3. Email (Context-Aware)
        email = self.email_gen.fabricate(identity)
        
        # Extract the "Handle" part of the email for username/password consistency
        # e.g., 'alex.lucky99@gmail.com' -> 'alex.lucky99'
        email_handle = email.split("@")[0]
        
        # 4. Username (Derived from Email Handle)
        # Casinos often ban dots in usernames, so we clean it
        username = email_handle.replace(".", "").replace("_", "")
        # If too short, append year
        if len(username) < 5:
            username += identity['dob_complex']['year_short']
            
        # 5. Password (Derived from Identity/Handle)
        password = self.pass_gen.generate(identity, email_handle=username)
        
        # 6. Bundle Everything
        persona = {
            "identity": identity,
            "contact": {
                "email": email,
                "phone": phone,
                "phone_national": self.phone_gen.generate(country_code, identity.get('state'), "NATIONAL"), # Useful for typing
                "phone_raw": self.phone_gen.generate(country_code, identity.get('state'), "RAW")
            },
            "account": {
                "username": username,
                "password": password
            }
        }
        
        self._log_summary(persona)
        return persona

    def _log_summary(self, p):
        i = p['identity']
        logger.success(
            f"👤 Persona Created: {i['first_name']} {i['last_name']} ({i['dob_year']})\n"
            f"   📍 Loc: {i['city']}, {i['state']} ({i['country']})\n"
            f"   📧 Email: {p['contact']['email']}\n"
            f"   📱 Phone: {p['contact']['phone']}\n"
            f"   🔑 Pass: {p['account']['password']}"
        )

# --- Usage in Production ---
# factory = PersonaFactory(catchall_domains=["my-domain.com"])
# persona = factory.create_persona("US", "NY")
