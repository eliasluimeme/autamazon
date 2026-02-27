"""
Identity Pool - Pre-warmed Identity Generation

Generates identities BEFORE browser launch to eliminate the performance gap
between opening a profile and starting automation.

Architecture:
    - Pre-generates a configurable pool of identities in a background thread
    - Thread-safe queue for concurrent access
    - Identities include both Outlook-ready and Amazon-ready data
    - Deterministic: one identity per profile, no conflicts

Usage:
    pool = IdentityPool(pool_size=5)
    pool.warm_up()  # Pre-generate identities
    
    identity = pool.acquire()  # Get a ready identity (blocks if pool empty)
    # ... use identity for automation ...
    pool.release(identity, success=True)  # Mark as used
"""

import threading
import queue
import time
from dataclasses import dataclass, field
from typing import Optional, Dict, Any
from enum import Enum
from loguru import logger


class IdentityState(Enum):
    """Lifecycle states for a pooled identity."""
    GENERATED = "generated"       # Created, waiting in pool
    ACQUIRED = "acquired"         # Claimed by a worker
    OUTLOOK_DONE = "outlook_done" # Outlook account created
    ACTIVE = "active"             # In use by automation
    COMPLETED = "completed"       # Successfully used
    FAILED = "failed"             # Failed, may be recyclable
    DISCARDED = "discarded"       # Permanently unusable


@dataclass
class PooledIdentity:
    """
    A complete, pre-generated identity bundle ready for immediate use.
    
    Contains all data needed for both Outlook signup AND Amazon registration,
    so no generation occurs during browser automation.
    """
    # Core identity
    firstname: str = ""
    lastname: str = ""
    email_handle: str = ""
    password: str = ""
    
    # Date of birth
    dob_month: str = ""
    dob_day: str = ""
    dob_year: str = ""
    
    # Extended identity (for Amazon)
    address_line1: str = ""
    city: str = ""
    zip_code: str = ""
    region_state: str = ""  # Geographic state/province (e.g., "Victoria", "NY")
    country: str = ""
    phone: str = ""
    country_code: str = "US"
    
    # Lifecycle tracking
    lifecycle_state: str = "generated"  # Identity lifecycle state
    profile_id: Optional[str] = None   # Bound profile (once acquired)
    created_at: float = field(default_factory=time.time)
    acquired_at: Optional[float] = None
    
    # Full outlook email (set after Outlook signup)
    outlook_email: Optional[str] = None
    
    def to_outlook_dict(self) -> dict:
        """Format for Outlook signup flow (matches existing interface)."""
        return {
            "firstname": self.firstname,
            "lastname": self.lastname,
            "email_handle": self.email_handle,
            "password": self.password,
            "dob_month": self.dob_month,
            "dob_day": self.dob_day,
            "dob_year": self.dob_year,
        }
    
    def to_amazon_identity(self):
        """Convert to Amazon Identity object (matches existing interface)."""
        try:
            from amazon.identity_manager import Identity
        except ImportError:
            from identity_manager import Identity
        return Identity(
            firstname=self.firstname,
            lastname=self.lastname,
            email=self.outlook_email or f"{self.email_handle}@outlook.com",
            password=self.password,
            address_line1=self.address_line1 or "215 Somerton Rd",
            city=self.city or "Melbourne",
            zip_code=self.zip_code or "3048",
            state=self.region_state or "Victoria",
            country=self.country or "Australia",
            phone=self.phone or "399304444",
        )


class IdentityPool:
    """
    Thread-safe pool of pre-generated identities.
    
    Pre-generates identities in a background thread so they're ready
    the instant a browser profile launches. This eliminates the 3-5s
    identity generation gap that previously occurred mid-automation.
    
    Thread Safety:
        - Uses Queue for thread-safe identity dispensing
        - Background generation thread fills pool asynchronously
        - Lock protects tracking data structures
    """
    
    def __init__(self, pool_size: int = 5, country_code: str = "US"):
        self.pool_size = pool_size
        self.country_code = country_code
        
        # Thread-safe queue for ready identities
        self._ready_queue: queue.Queue[PooledIdentity] = queue.Queue(maxsize=pool_size * 2)
        
        # Tracking
        self._lock = threading.Lock()
        self._active: Dict[str, PooledIdentity] = {}   # profile_id -> identity
        self._completed: list = []
        self._failed: list = []
        
        # Background generation
        self._gen_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._total_generated = 0
        
    def warm_up(self, count: int = None):
        """
        Pre-generate identities synchronously (blocking).
        Call this BEFORE starting any automation.
        
        Args:
            count: Number to pre-generate (defaults to pool_size)
        """
        target = count or self.pool_size
        logger.info(f"🔥 Warming up identity pool ({target} identities)...")
        
        start = time.time()
        generated = 0
        
        for _ in range(target):
            try:
                identity = self._generate_one()
                if identity:
                    self._ready_queue.put(identity, timeout=5)
                    generated += 1
            except Exception as e:
                logger.error(f"Identity generation failed: {e}")
                
        elapsed = time.time() - start
        logger.success(
            f"✅ Identity pool warmed: {generated}/{target} identities "
            f"in {elapsed:.1f}s ({elapsed/max(generated,1)*1000:.0f}ms each)"
        )
    
    def start_background_generation(self):
        """Start background thread to keep pool filled."""
        if self._gen_thread and self._gen_thread.is_alive():
            return
            
        self._stop_event.clear()
        self._gen_thread = threading.Thread(
            target=self._background_generator,
            daemon=True,
            name="identity-pool-generator"
        )
        self._gen_thread.start()
        logger.info("🔄 Background identity generation started")
    
    def stop_background_generation(self):
        """Stop background generation thread."""
        self._stop_event.set()
        if self._gen_thread:
            self._gen_thread.join(timeout=5)
            
    def acquire(self, profile_id: str, timeout: float = 30) -> Optional[PooledIdentity]:
        """
        Get a pre-generated identity for a specific profile.
        
        Blocks until an identity is available or timeout expires.
        The identity is bound to the profile_id for tracking.
        
        Args:
            profile_id: AdsPower profile ID to bind
            timeout: Max seconds to wait
            
        Returns:
            PooledIdentity or None if timeout
        """
        try:
            identity = self._ready_queue.get(timeout=timeout)
            identity.profile_id = profile_id
            identity.acquired_at = time.time()
            identity.lifecycle_state = IdentityState.ACQUIRED.value
            
            with self._lock:
                self._active[profile_id] = identity
            
            logger.info(
                f"📋 Identity acquired for profile {profile_id}: "
                f"{identity.firstname} {identity.lastname} ({identity.email_handle})"
            )
            return identity
            
        except queue.Empty:
            logger.error(f"Identity pool exhausted! No identity available for {profile_id}")
            return None
    
    def mark_outlook_done(self, profile_id: str, email: str):
        """Mark that Outlook account is created for this identity."""
        with self._lock:
            if profile_id in self._active:
                self._active[profile_id].outlook_email = email
                self._active[profile_id].lifecycle_state = IdentityState.OUTLOOK_DONE.value
                logger.info(f"📧 Identity for {profile_id} → Outlook done: {email}")
    
    def release(self, profile_id: str, success: bool = True, notes: str = None):
        """
        Release an identity back after use.
        
        Args:
            profile_id: Profile that was using this identity
            success: Whether automation succeeded
            notes: Optional notes for tracking
        """
        with self._lock:
            identity = self._active.pop(profile_id, None)
            if not identity:
                return
                
            if success:
                identity.lifecycle_state = IdentityState.COMPLETED.value
                self._completed.append(identity)
                logger.info(f"✅ Identity completed for {profile_id}")
            else:
                identity.lifecycle_state = IdentityState.FAILED.value
                self._failed.append(identity)
                logger.warning(f"❌ Identity failed for {profile_id}: {notes}")
    
    def get_stats(self) -> dict:
        """Get pool statistics."""
        with self._lock:
            return {
                "ready": self._ready_queue.qsize(),
                "active": len(self._active),
                "completed": len(self._completed),
                "failed": len(self._failed),
                "total_generated": self._total_generated,
            }
    
    @property
    def available(self) -> int:
        """Number of ready identities in pool."""
        return self._ready_queue.qsize()
    
    def _generate_one(self) -> Optional[PooledIdentity]:
        """Generate a single identity using existing shared modules."""
        try:
            import random
            import string
            
            # Cache generator instances on first call (avoid re-init per identity)
            if not hasattr(self, '_ig'):
                try:
                    from modules.identity_generator import IdentityGenerator
                    from modules.email_fabricator import EmailFabricator
                    self._ig = IdentityGenerator()
                    self._ef = EmailFabricator()
                    self._use_shared = True
                except ImportError:
                    self._use_shared = False
                    try:
                        from faker import Faker
                        self._faker = Faker()
                    except ImportError:
                        self._faker = None
            
            if self._use_shared:
                base = self._ig.generate_identity(self.country_code)
                full_email = self._ef.fabricate(base, force_domain="outlook.com")
                email_handle = full_email.split("@")[0]
            elif self._faker:
                fake = self._faker
                base = {
                    "first_name": fake.first_name(),
                    "last_name": fake.last_name(),
                    "dob_day": str(random.randint(1, 28)),
                    "dob_month": str(random.randint(1, 12)),
                    "dob_year": str(random.randint(1980, 2000)),
                    "address": fake.street_address(),
                    "city": fake.city(),
                    "zip": fake.postcode(),
                    "state": fake.state(),
                    "country": self.country_code,
                }
                fname = base["first_name"].lower()
                lname = base["last_name"].lower()
                email_handle = f"{fname}.{lname}{random.randint(100, 9999)}"
            else:
                # Last resort: pure random
                base = {
                    "first_name": f"User{random.randint(100, 999)}",
                    "last_name": f"Test{random.randint(100, 999)}",
                    "dob_day": str(random.randint(1, 28)),
                    "dob_month": str(random.randint(1, 12)),
                    "dob_year": str(random.randint(1980, 2000)),
                    "country": self.country_code,
                }
                email_handle = f"user{random.randint(10000, 99999)}"
            
            # Sanitize: email handle must not start with digit
            while email_handle and email_handle[0].isdigit():
                email_handle = email_handle[1:]
            if not email_handle or len(email_handle) < 3:
                prefix = random.choice(string.ascii_lowercase)
                email_handle = f"{prefix}user{random.randint(100, 999)}"
            
            # Generate strong password
            chars = string.ascii_letters + string.digits + "!@#$%^&*"
            password = "".join(random.choice(chars) for _ in range(14))
            
            identity = PooledIdentity(
                firstname=base.get("first_name", ""),
                lastname=base.get("last_name", ""),
                email_handle=email_handle,
                password=password,
                dob_month=str(base.get("dob_month", str(random.randint(1, 12)))),
                dob_day=str(base.get("dob_day", str(random.randint(1, 28)))),
                dob_year=str(base.get("dob_year", str(random.randint(1980, 2000)))),
                address_line1=base.get("address", "215 Somerton Rd"),
                city=base.get("city", "Melbourne"),
                zip_code=base.get("zip", "3048"),
                country=base.get("country", self.country_code),
                phone=base.get("phone", "399304444"),
                country_code=self.country_code,
            )
            
            self._total_generated += 1
            return identity
            
        except Exception as e:
            logger.error(f"Identity generation error: {e}")
            return None
    
    def _background_generator(self):
        """Background thread that keeps the pool filled."""
        logger.debug("Background identity generator running")
        
        while not self._stop_event.is_set():
            try:
                # Only generate if pool is running low
                if self._ready_queue.qsize() < self.pool_size:
                    identity = self._generate_one()
                    if identity:
                        try:
                            self._ready_queue.put(identity, timeout=2)
                        except queue.Full:
                            pass  # Pool is full, skip
                else:
                    # Pool is full, sleep before checking again
                    self._stop_event.wait(timeout=2)
                    
            except Exception as e:
                logger.error(f"Background generation error: {e}")
                self._stop_event.wait(timeout=5)
                
        logger.debug("Background identity generator stopped")
