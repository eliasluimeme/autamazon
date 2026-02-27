"""
Profile Lifecycle Manager

Implements a deterministic state machine for browser profile lifecycle management.
Replaces implicit state tracking with explicit, observable states.

Profile States:
    IDLE       → Profile exists but no browser running
    LAUNCHING  → Browser start requested, waiting for CDP
    READY      → Browser running, connected, validated
    WORKING    → Automation task in progress
    COOLING    → Task done, browser still open for cleanup
    STOPPING   → Browser shutdown in progress
    ERROR      → Unrecoverable error state
    COMPLETED  → Successfully finished all tasks

State Transitions:
    IDLE → LAUNCHING → READY → WORKING → COOLING → STOPPING → IDLE
                         ↓                    ↓
                       ERROR               ERROR

This ensures:
    - One account per profile (strict isolation)
    - No ghost sessions
    - No browser fingerprint conflicts
    - No parallel usage conflicts
    - Deterministic cleanup on failure
"""

import time
import threading
from enum import Enum
from dataclasses import dataclass, field
from typing import Optional, Dict, Callable, List
from loguru import logger


class ProfileState(Enum):
    """Deterministic profile lifecycle states."""
    IDLE = "idle"
    LAUNCHING = "launching"
    READY = "ready"
    WORKING = "working"
    COOLING = "cooling_down"
    STOPPING = "stopping"
    ERROR = "error"
    COMPLETED = "completed"


# Valid state transitions
VALID_TRANSITIONS = {
    ProfileState.IDLE: [ProfileState.LAUNCHING],
    ProfileState.LAUNCHING: [ProfileState.READY, ProfileState.ERROR],
    ProfileState.READY: [ProfileState.WORKING, ProfileState.STOPPING, ProfileState.ERROR],
    ProfileState.WORKING: [ProfileState.COOLING, ProfileState.ERROR],
    ProfileState.COOLING: [ProfileState.STOPPING, ProfileState.WORKING, ProfileState.ERROR],
    ProfileState.STOPPING: [ProfileState.IDLE, ProfileState.COMPLETED, ProfileState.ERROR],
    ProfileState.ERROR: [ProfileState.STOPPING, ProfileState.IDLE],
    ProfileState.COMPLETED: [ProfileState.IDLE],  # Can be recycled
}


@dataclass
class ProfileMetrics:
    """Performance metrics for a single profile."""
    launch_start: Optional[float] = None
    launch_end: Optional[float] = None
    task_start: Optional[float] = None
    task_end: Optional[float] = None
    error_count: int = 0
    retry_count: int = 0
    state_transitions: List[tuple] = field(default_factory=list)
    
    @property
    def launch_duration(self) -> Optional[float]:
        if self.launch_start and self.launch_end:
            return self.launch_end - self.launch_start
        return None
    
    @property
    def task_duration(self) -> Optional[float]:
        if self.task_start and self.task_end:
            return self.task_end - self.task_start
        return None


@dataclass
class ManagedProfile:
    """A profile with full lifecycle management."""
    profile_id: str
    state: ProfileState = ProfileState.IDLE
    
    # Resources (set when READY)
    browser_manager: object = None   # OpSecBrowserManager
    page: object = None              # Playwright page
    device: object = None            # DeviceAdapter
    identity: object = None          # PooledIdentity
    
    # Tracking
    metrics: ProfileMetrics = field(default_factory=ProfileMetrics)
    last_error: Optional[str] = None
    current_task: Optional[str] = None
    
    # Lock for thread-safe state transitions
    _lock: threading.Lock = field(default_factory=threading.Lock)
    
    def transition_to(self, new_state: ProfileState, reason: str = "") -> bool:
        """
        Attempt a state transition with validation.
        
        Args:
            new_state: Target state
            reason: Human-readable reason for transition
            
        Returns:
            True if transition was valid and executed
        """
        with self._lock:
            valid_targets = VALID_TRANSITIONS.get(self.state, [])
            
            if new_state not in valid_targets:
                logger.error(
                    f"❌ Invalid state transition for {self.profile_id}: "
                    f"{self.state.value} → {new_state.value} "
                    f"(valid: {[s.value for s in valid_targets]})"
                )
                return False
            
            old_state = self.state
            self.state = new_state
            self.metrics.state_transitions.append(
                (old_state.value, new_state.value, time.time(), reason)
            )
            
            # Update metrics based on transition
            if new_state == ProfileState.LAUNCHING:
                self.metrics.launch_start = time.time()
            elif new_state == ProfileState.READY:
                self.metrics.launch_end = time.time()
            elif new_state == ProfileState.WORKING:
                self.metrics.task_start = time.time()
            elif new_state in (ProfileState.COOLING, ProfileState.COMPLETED):
                self.metrics.task_end = time.time()
            elif new_state == ProfileState.ERROR:
                self.metrics.error_count += 1
                self.last_error = reason
            
            logger.info(
                f"🔄 [{self.profile_id}] {old_state.value} → {new_state.value}"
                f"{f' ({reason})' if reason else ''}"
            )
            return True
    
    @property
    def is_busy(self) -> bool:
        return self.state in (ProfileState.LAUNCHING, ProfileState.WORKING)
    
    @property
    def is_available(self) -> bool:
        return self.state == ProfileState.IDLE
    
    @property
    def needs_cleanup(self) -> bool:
        return self.state in (ProfileState.ERROR, ProfileState.COOLING)


class ProfileLifecycleManager:
    """
    Centralized manager for all profile lifecycles.
    
    Ensures:
        - No two tasks run on the same profile simultaneously
        - Clean startup and shutdown sequences
        - Resource tracking and cleanup
        - Performance metrics collection
    """
    
    def __init__(self, max_concurrent: int = 3):
        self.max_concurrent = max_concurrent
        self._profiles: Dict[str, ManagedProfile] = {}
        self._lock = threading.Lock()
        self._on_state_change: Optional[Callable] = None
        
    def register_profile(self, profile_id: str) -> ManagedProfile:
        """Register a profile for lifecycle management."""
        with self._lock:
            if profile_id in self._profiles:
                existing = self._profiles[profile_id]
                if existing.state == ProfileState.COMPLETED:
                    # Reset for reuse
                    existing.state = ProfileState.IDLE
                    existing.metrics = ProfileMetrics()
                    existing.last_error = None
                    existing.current_task = None
                return existing
            
            profile = ManagedProfile(profile_id=profile_id)
            self._profiles[profile_id] = profile
            logger.info(f"📋 Registered profile: {profile_id}")
            return profile
    
    def get_profile(self, profile_id: str) -> Optional[ManagedProfile]:
        """Get a managed profile by ID."""
        return self._profiles.get(profile_id)
    
    @property
    def active_count(self) -> int:
        """Number of profiles currently running tasks."""
        return sum(1 for p in self._profiles.values() if p.is_busy)
    
    @property
    def can_launch_more(self) -> bool:
        """Whether we can launch more profiles."""
        return self.active_count < self.max_concurrent
    
    def get_profiles_in_state(self, state: ProfileState) -> List[ManagedProfile]:
        """Get all profiles in a specific state."""
        return [p for p in self._profiles.values() if p.state == state]
    
    def cleanup_profile(self, profile_id: str):
        """
        Force cleanup of a profile's resources.
        Used for error recovery and graceful shutdown.
        """
        profile = self._profiles.get(profile_id)
        if not profile:
            return
        
        # Skip if already fully cleaned up
        if profile.state in (ProfileState.IDLE, ProfileState.COMPLETED) and not profile.browser_manager:
            return
        
        logger.info(f"🧹 Cleaning up profile {profile_id} (state: {profile.state.value})")
        
        # Stop browser if running
        if profile.browser_manager:
            try:
                profile.browser_manager.stop_browser()
            except Exception as e:
                logger.warning(f"Browser cleanup error for {profile_id}: {e}")
            finally:
                profile.browser_manager = None
                profile.page = None
                profile.device = None
        
        # Transition to appropriate final state
        if profile.state == ProfileState.ERROR:
            profile.transition_to(ProfileState.IDLE, "Cleaned up after error")
        elif profile.state in (ProfileState.IDLE, ProfileState.COMPLETED):
            pass  # Already in a terminal state, no transition needed
        elif profile.state in (ProfileState.WORKING, ProfileState.COOLING):
            profile.transition_to(ProfileState.COOLING if profile.state == ProfileState.WORKING else profile.state, "Force cleanup")
            profile.transition_to(ProfileState.STOPPING, "Force cleanup")
            profile.transition_to(ProfileState.IDLE, "Cleanup complete")
        elif profile.state in (ProfileState.LAUNCHING, ProfileState.READY):
            profile.transition_to(ProfileState.ERROR, "Force cleanup")
            profile.transition_to(ProfileState.IDLE, "Cleanup complete")
        elif profile.state == ProfileState.STOPPING:
            profile.transition_to(ProfileState.IDLE, "Cleanup complete")
    
    def cleanup_all(self):
        """Cleanup all managed profiles. Called on shutdown."""
        logger.info(f"🧹 Cleaning up all profiles ({len(self._profiles)} registered)...")
        for profile_id in list(self._profiles.keys()):
            self.cleanup_profile(profile_id)
        logger.success("✅ All profiles cleaned up")
    
    def get_metrics_summary(self) -> dict:
        """Get aggregated metrics across all profiles."""
        metrics = {
            "total_profiles": len(self._profiles),
            "by_state": {},
            "avg_launch_time": 0,
            "avg_task_time": 0,
            "total_errors": 0,
            "total_retries": 0,
        }
        
        launch_times = []
        task_times = []
        
        for state in ProfileState:
            count = sum(1 for p in self._profiles.values() if p.state == state)
            if count > 0:
                metrics["by_state"][state.value] = count
        
        for p in self._profiles.values():
            metrics["total_errors"] += p.metrics.error_count
            metrics["total_retries"] += p.metrics.retry_count
            
            if p.metrics.launch_duration:
                launch_times.append(p.metrics.launch_duration)
            if p.metrics.task_duration:
                task_times.append(p.metrics.task_duration)
        
        if launch_times:
            metrics["avg_launch_time"] = sum(launch_times) / len(launch_times)
        if task_times:
            metrics["avg_task_time"] = sum(task_times) / len(task_times)
            
        return metrics
