import os
import json
from loguru import logger
from amazon.identity_manager import Identity

class SessionState:
    """
    Manages the persistent state of a profile's automation run.
    Ensures that if the script crashes, it can resume from the last completed flag.
    """
    def __init__(self, profile_id: str):
        self.profile_id = profile_id
        
        # Setup file paths
        base_dir = os.path.dirname(os.path.abspath(__file__))
        self.sessions_dir = os.path.abspath(os.path.join(base_dir, '..', 'data', 'sessions'))
        os.makedirs(self.sessions_dir, exist_ok=True)
        self.filepath = os.path.join(self.sessions_dir, f"{profile_id}.json")
        
        # Default State
        self.status = "PROCESSING"
        self.platform = "unknown"
        self.completion_flags = {
            "outlook_created": False,
            "product_selected": False,
            "amazon_signup": False,
            "dev_registration": False,
            "2fa_enabled": False
        }
        self.identity: Identity | None = None
        
        # Initialize
        self.load()
        
    def load(self):
        """Loads state from JSON file if it exists."""
        if os.path.exists(self.filepath):
            try:
                with open(self.filepath, 'r') as f:
                    data = json.load(f)
                    
                self.status = data.get("status", self.status)
                self.platform = data.get("platform", self.platform)
                
                flags = data.get("completion_flags", {})
                self.completion_flags.update(flags)
                
                identity_data = data.get("identity")
                if identity_data:
                    # Identity dataclass can be initialized with kw fields
                    # Let's extract only the active fields to prevent arg errors
                    self.identity = Identity(
                        firstname=identity_data.get("firstname", ""),
                        lastname=identity_data.get("lastname", ""),
                        email=identity_data.get("email", ""),
                        password=identity_data.get("password", ""),
                        address_line1=identity_data.get("address_line1", "215 Somerton Rd"),
                        city=identity_data.get("city", "Melbourne"),
                        zip_code=identity_data.get("zip_code", "3048"),
                        state=identity_data.get("state", "Victoria"),
                        country=identity_data.get("country", "Australia"),
                        phone=identity_data.get("phone", "399304444"),
                        two_fa_secret=identity_data.get("two_fa_secret")
                    )
                logger.info(f"Loaded existing session state for {self.profile_id}")
            except Exception as e:
                logger.error(f"Failed to load session state for {self.profile_id}: {e}")
                self.save() # Overwrite corrupted file
        else:
            self.save()
            
    def save(self):
        """Saves current state to JSON file."""
        ident_dict = None
        if self.identity:
            ident_dict = self.identity.to_dict()
            ident_dict["two_fa_secret"] = self.identity.two_fa_secret
            
        data = {
            "profile_id": self.profile_id,
            "status": self.status,
            "platform": self.platform,
            "completion_flags": self.completion_flags,
            "identity": ident_dict
        }
        
        try:
            # Atomic save to prevent corruption if script kills mid-write
            tmp_filepath = f"{self.filepath}.tmp"
            with open(tmp_filepath, 'w') as f:
                json.dump(data, f, indent=4)
            os.replace(tmp_filepath, self.filepath)
        except Exception as e:
            logger.error(f"Failed to save session state for {self.profile_id}: {e}")
            
    def update_flag(self, flag_name: str, value: bool = True):
        """Syntactic sugar for updating a flag and saving instantly."""
        if flag_name in self.completion_flags:
            self.completion_flags[flag_name] = value
            self.save()
            logger.info(f"Session state updated: {flag_name} = {value}")
        else:
            logger.error(f"Attempted to update unknown completion flag: {flag_name}")
            
    def update_identity(self, identity: Identity):
        self.identity = identity
        self.save()

    def set_status(self, status: str):
        self.status = status
        self.save()
