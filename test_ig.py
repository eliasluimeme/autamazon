import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), './')))
from modules.identity_generator import IdentityGenerator
from modules.email_fabricator import EmailFabricator

print("Instantiating IdentityGenerator...")
ig = IdentityGenerator()
print("Generating identity...")
identity = ig.generate_identity("US")
print(identity)

print("Instantiating EmailFabricator...")
ef = EmailFabricator()
email = ef.fabricate(identity, force_domain="outlook.com")
print(email)
