"""
Identity Manager for Amazon Automation

Manages user credentials for account creation:
- Reads identities from a source file (one per line)
- Tracks used identities in a separate file
- Format: firstname:lastname:email:password
"""

import os
import threading
from dataclasses import dataclass
from typing import Optional
from loguru import logger


@dataclass
class Identity:
    """User identity for account creation."""
    firstname: str
    lastname: str
    email: str
    password: str
    address_line1: str = "215 Somerton Rd"
    city: str = "Melbourne"
    zip_code: str = "3048"
    state: str = "Victoria"
    country: str = "Australia"
    phone: str = "399304444"
    two_fa_secret: Optional[str] = None
    
    # Country name to ISO code mapping
    COUNTRY_CODES = {
        "United States": "US",
        "Australia": "AU",
        "United Kingdom": "GB",
        "Canada": "CA",
        "Germany": "DE",
        "France": "FR",
        "Japan": "JP",
        "India": "IN",
        "Brazil": "BR",
        "Mexico": "MX",
    }
    
    @property
    def full_name(self) -> str:
        """Get full name (First Last)."""
        return f"{self.firstname.title()} {self.lastname.title()}"
    
    @property
    def country_code(self) -> str:
        """Get ISO country code for phone prefix selection."""
        return self.COUNTRY_CODES.get(self.country, "US")
    
    def to_line(self) -> str:
        """Convert to file line format."""
        base = f"{self.firstname}:{self.lastname}:{self.email}:{self.password}:{self.address_line1}:{self.city}:{self.zip_code}:{self.state}:{self.country}:{self.phone}"
        if self.two_fa_secret:
            base += f":{self.two_fa_secret}"
        return base
    
    @classmethod
    def from_line(cls, line: str) -> Optional['Identity']:
        """Parse identity from file line."""
        line = line.strip()
        if not line or line.startswith('#'):
            return None
        
        parts = line.split(':')
        if len(parts) < 4:
            logger.warning(f"Invalid identity format: {line}")
            return None
        
        # Core identity
        firstname = parts[0].strip()
        lastname = parts[1].strip()
        email = parts[2].strip()
        password = parts[3].strip()
        
        # Sanitization: Email/Handle should never start with a number (Amazon restriction)
        if email and email[0].isdigit():
            logger.warning(f"Email {email} starts with a digit, sanitizing...")
            # If it's a full email, try to remove leading digits from the local part
            local_part, domain = email.split('@') if '@' in email else (email, 'gmail.com')
            while local_part and local_part[0].isdigit():
                local_part = local_part[1:]
            if not local_part:
                local_part = "user"
            email = f"{local_part}@{domain}"
        
        identity = cls(
            firstname=firstname,
            lastname=lastname,
            email=email,
            password=password
        )
        
        # Optional address fields ...
        if len(parts) >= 10:
            identity.address_line1 = parts[4].strip()
            identity.city = parts[5].strip()
            identity.zip_code = parts[6].strip()
            identity.state = parts[7].strip()
            identity.country = parts[8].strip()
            identity.phone = parts[9].strip()
            
        # Optional 2FA Secret
        if len(parts) >= 11:
            identity.two_fa_secret = parts[10].strip()
            
        return identity
    
    def to_dict(self) -> dict:
        """Convert to dict for form filling."""
        return {
            'name': self.full_name,
            'firstname': self.firstname,
            'lastname': self.lastname,
            'email': self.email,
            'password': self.password,
            'address_line1': self.address_line1,
            'city': self.city,
            'zip_code': self.zip_code,
            'state': self.state,
            'country': self.country,
            'phone': self.phone,
        }


class IdentityManager:
    """
    Manages identity queue for Amazon signups.
    
    Reads identities from source file, marks them as used,
    and moves them to a used file.
    """
    
    _lock = threading.Lock()
    
    def __init__(self, 
                 source_file: str = None,
                 used_file: str = None):
        """
        Initialize identity manager.
        
        Args:
            source_file: Path to file with available identities
            used_file: Path to file for tracking used identities
        """
        # Default paths
        base_dir = os.path.dirname(os.path.abspath(__file__))
        
        self.source_file = source_file or os.path.join(base_dir, 'data', 'identities.txt')
        self.used_file = used_file or os.path.join(base_dir, 'data', 'identities_used.txt')
        
        # Ensure data directory exists
        os.makedirs(os.path.dirname(self.source_file), exist_ok=True)
        
        # Ensure files exist
        for filepath in [self.source_file, self.used_file]:
            if not os.path.exists(filepath):
                open(filepath, 'a').close()
        
        logger.debug(f"IdentityManager initialized")
        logger.debug(f"  Source: {self.source_file}")
        logger.debug(f"  Used: {self.used_file}")
    
    def get_next_identity(self) -> Optional[Identity]:
        """
        Get the next available identity.
        
        Reads the first line from source file, removes it,
        and returns the parsed identity.
        
        Returns:
            Identity object or None if no identities available
        """
        with self._lock:
            try:
                # Read all lines from source
                with open(self.source_file, 'r') as f:
                    lines = f.readlines()
                
                if not lines:
                    logger.warning("No identities available in source file")
                    return None
                
                # Find first valid identity
                identity = None
                identity_line = None
                remaining_lines = []
                
                for i, line in enumerate(lines):
                    if identity is None:
                        parsed = Identity.from_line(line)
                        if parsed:
                            identity = parsed
                            identity_line = line.strip()
                            remaining_lines = lines[i+1:]
                            break
                    remaining_lines.append(line)
                
                if identity is None:
                    logger.warning("No valid identities found in source file")
                    return None
                
                # Write remaining lines back to source
                with open(self.source_file, 'w') as f:
                    f.writelines(remaining_lines)
                
                logger.info(f"📋 Retrieved identity: {identity.email}")
                logger.debug(f"  Remaining identities: {len(remaining_lines)}")
                
                return identity
                
            except Exception as e:
                logger.error(f"Failed to get identity: {e}")
                return None
    
    def mark_as_used(self, identity: Identity, success: bool = True, 
                     notes: str = None) -> bool:
        """
        Mark an identity as used.
        
        Args:
            identity: Identity that was used
            success: Whether the signup was successful
            notes: Optional notes (e.g., error message)
            
        Returns:
            True if successfully recorded
        """
        with self._lock:
            try:
                status = "SUCCESS" if success else "FAILED"
                line = f"{identity.to_line()}:{status}"
                if notes:
                    line += f":{notes}"
                
                with open(self.used_file, 'a') as f:
                    f.write(line + '\n')
                
                logger.info(f"✓ Identity marked as used: {identity.email} ({status})")
                return True
                
            except Exception as e:
                logger.error(f"Failed to mark identity as used: {e}")
                return False
    
    def get_available_count(self) -> int:
        """Get number of available identities."""
        try:
            with open(self.source_file, 'r') as f:
                lines = [l for l in f.readlines() if l.strip() and not l.startswith('#')]
            return len(lines)
        except:
            return 0
    
    def get_used_count(self) -> int:
        """Get number of used identities."""
        try:
            with open(self.used_file, 'r') as f:
                lines = [l for l in f.readlines() if l.strip()]
            return len(lines)
        except:
            return 0
    
    def peek_next_identity(self) -> Optional[Identity]:
        """
        Preview the next identity without removing it.
        
        Returns:
            Identity object or None
        """
        try:
            with open(self.source_file, 'r') as f:
                for line in f:
                    identity = Identity.from_line(line)
                    if identity:
                        return identity
            return None
        except:
            return None
    
    def return_identity(self, identity: Identity) -> bool:
        """
        Return an identity to the front of the queue.
        
        Use this if signup failed and you want to retry later.
        
        Args:
            identity: Identity to return
            
        Returns:
            True if successful
        """
        with self._lock:
            try:
                # Read current lines
                with open(self.source_file, 'r') as f:
                    lines = f.readlines()
                
                # Prepend the identity
                with open(self.source_file, 'w') as f:
                    f.write(identity.to_line() + '\n')
                    f.writelines(lines)
                
                logger.info(f"↩ Identity returned to queue: {identity.email}")
                return True
                
            except Exception as e:
                logger.error(f"Failed to return identity: {e}")
                return False

    def find_identity_by_email(self, email: str) -> Optional[Identity]:
        """
        Search for an identity by email in both used and source files.
        Useful for recovering credentials when re-auth prompt appears for a specific user.
        """
        try:
            target_email = email.lower().strip()
            
            # Check used identities first (most likely scenario for re-auth)
            with open(self.used_file, 'r') as f:
                for line in f:
                    identity = Identity.from_line(line)
                    if identity and identity.email.lower().strip() == target_email:
                        logger.info(f"✓ Found identity in used file: {identity.email}")
                        return identity
            
            # Check source file
            with open(self.source_file, 'r') as f:
                for line in f:
                    identity = Identity.from_line(line)
                    if identity and identity.email.lower().strip() == target_email:
                        logger.info(f"✓ Found identity in source file: {identity.email}")
                        return identity
                        
            return None
        except Exception as e:
            logger.error(f"Failed to search for identity: {e}")
            return None


# Global instance
_manager: Optional[IdentityManager] = None


def get_identity_manager() -> IdentityManager:
    """Get or create the global identity manager."""
    global _manager
    if _manager is None:
        _manager = IdentityManager()
    return _manager


def get_next_identity() -> Optional[Identity]:
    """Convenience function to get next identity."""
    return get_identity_manager().get_next_identity()


def mark_identity_used(identity: Identity, success: bool = True, 
                       notes: str = None) -> bool:
    """Convenience function to mark identity as used."""
    return get_identity_manager().mark_as_used(identity, success, notes)


def find_identity_by_email(email: str) -> Optional[Identity]:
    """Convenience function to find identity by email."""
    return get_identity_manager().find_identity_by_email(email)
