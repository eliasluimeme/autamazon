# V3 Architecture: Performance & Resource Optimization

## Executive Summary

This document describes the V3 architecture redesign of the Amazon browser automation platform.
The primary goals are:

1. **Eliminate the identity generation gap** (3-5s per profile saved)
2. **Reduce RAM usage** (~50MB saved per concurrent profile)
3. **Deterministic profile lifecycle** (no ghost sessions, no lock conflicts)
4. **Graceful process management** (no zombie processes)
5. **Observable system** (metrics, monitoring, traceability)

---

## Before vs After

| Metric | V2 (Current) | V3 (Optimized) | Improvement |
|--------|:---:|:---:|:---:|
| Identity Generation | During browser session | Pre-warmed pool | -3-5s/profile |
| RAM per profile | ~150MB (subprocess) | ~100MB (thread) | -33% |
| Process count per profile | 3 (orchestrator + python + node) | 1 (thread + shared node) | -66% |
| Zombie risk | High (SIGKILL) | Low (graceful shutdown) | ✅ |
| Profile state tracking | Implicit | State machine | ✅ |
| Lock conflicts | Race conditions via threading.Lock | Lifecycle manager | ✅ |
| Cleanup on crash | Partial | Full (lifecycle manager) | ✅ |
| Observability | Logs only | Metrics + logs | ✅ |

---

## Architecture Diagram (V3)

```
┌──────────────────────────────────────────────────────────┐
│                  orchestrator_v3.py                        │
│                 (Single Python Process)                    │
│                                                            │
│  ┌──────────────────┐  ┌──────────────────────────────┐  │
│  │  Identity Pool    │  │  Profile Lifecycle Manager    │  │
│  │                    │  │                                │  │
│  │  Pre-generates     │  │  State: IDLE → LAUNCHING →    │  │
│  │  identities in     │  │  READY → WORKING → COOLING → │  │
│  │  background thread │  │  STOPPING → COMPLETED         │  │
│  │                    │  │                                │  │
│  │  Queue[PooledId]   │  │  ManagedProfile[N]             │  │
│  └────────┬───────────┘  └──────────┬─────────────────────┘  │
│           │                          │                        │
│  ┌────────▼──────────────────────────▼─────────────────────┐ │
│  │              ThreadPoolExecutor (N workers)              │ │
│  │                                                           │ │
│  │  Worker Thread 1:                                         │ │
│  │    1. pool.acquire(profile_id) → identity (instant)       │ │
│  │    2. OpSecBrowserManager.start_browser()                 │ │
│  │    3. outlook_signup_with_identity(identity) ← KEY        │ │
│  │    4. amazon_signup, dev_reg, 2fa                         │ │
│  │    5. cleanup + pool.release()                            │ │
│  │                                                           │ │
│  │  Worker Thread 2: [same pipeline]                         │ │
│  │  Worker Thread N: [same pipeline]                         │ │
│  └───────────────────────────────────────────────────────────┘ │
│                                                                │
│  ┌────────────────────────────────────────────────────────────┐│
│  │              Enhanced Cleanup (utils/cleanup.py)           ││
│  │  - Graceful shutdown (SIGTERM → timeout → SIGKILL)        ││
│  │  - Process tree traversal (kills children)                ││
│  │  - AdsPower API session cleanup                           ││
│  │  - Resource usage monitoring                              ││
│  └────────────────────────────────────────────────────────────┘│
└──────────────────────────────────────────────────────────────┘
```

---

## Key Optimizations Explained

### 1. Identity Pre-Generation (The Gap Fix)

**Problem (V2):**
```
Browser Launch (3s) → Navigate to Outlook (2s) → GENERATE IDENTITY (3-5s) → Fill Form
                                                   ^^^^^^^^^^^^^^^^^^^^^^^^
                                                   Browser is IDLE here!
```

**Solution (V3):**
```
GENERATE IDENTITY (background) → Browser Launch (3s) → Navigate → Fill Form (instant)
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
Happens BEFORE browser starts!
```

**Implementation**: `core/identity_pool.py`
- `IdentityPool.warm_up(N)` — generates N identities before any browser starts
- `IdentityPool.acquire(profile_id)` — returns pre-generated identity in <1ms
- Background thread keeps pool topped up during automation
- Thread-safe queue prevents lock contention

### 2. In-Process Worker Pool (RAM Reduction)

**Problem (V2):**
```python
# orchestrator.py - spawns N subprocess
process = await asyncio.create_subprocess_exec(sys.executable, "run.py", profile_id)
# Each subprocess: ~50MB base Python + ~50MB Playwright = ~100MB overhead
```

**Solution (V3):**
```python
# orchestrator_v3.py - uses ThreadPoolExecutor
with ThreadPoolExecutor(max_workers=N) as executor:
    executor.submit(run_profile_pipeline, profile_id, lifecycle, identity_pool)
# All workers share: 1 Python process, 1 identity pool, 1 lifecycle manager
```

**Savings**: For 5 concurrent profiles: ~250MB RAM saved

### 3. Profile Lifecycle State Machine

**Problem (V2):**
- No explicit state tracking
- `manager.stop_browser()` called ad-hoc
- If script crashes between browser start and stop, session orphaned
- `threading.Lock` in IdentityManager has no cross-process effect

**Solution (V3):**
```python
# core/profile_lifecycle.py
class ProfileState(Enum):
    IDLE        # No browser
    LAUNCHING   # Browser starting
    READY       # Browser connected
    WORKING     # Task in progress
    COOLING     # Task done, cleanup pending
    STOPPING    # Shutdown in progress
    ERROR       # Unrecoverable error
    COMPLETED   # All done

# Only valid transitions are allowed:
VALID_TRANSITIONS = {
    ProfileState.IDLE: [ProfileState.LAUNCHING],
    ProfileState.LAUNCHING: [ProfileState.READY, ProfileState.ERROR],
    # ...
}
```

Every state transition is atomic, logged, and timed. Invalid transitions are rejected.

### 4. Graceful Process Cleanup

**Problem (V2):**
```python
os.kill(proc.info['pid'], signal.SIGKILL)  # Immediate, no cleanup opportunity
```

**Solution (V3):**
```python
def graceful_kill(pid, timeout=5.0):
    proc.terminate()           # SIGTERM — process can save state
    proc.wait(timeout=timeout) # Wait for graceful exit
    proc.kill()                # SIGKILL only if still alive

def kill_process_tree(pid):
    children = parent.children(recursive=True)
    # Kill children bottom-up, then parent
```

---

## Files Changed / Added

| File | Status | Purpose |
|------|--------|---------|
| `core/identity_pool.py` | **NEW** | Pre-warmed identity generation pool |
| `core/profile_lifecycle.py` | **NEW** | Profile state machine & lifecycle manager |
| `orchestrator_v3.py` | **NEW** | In-process orchestrator with worker pool |
| `outlook/run.py` | **MODIFIED** | Added `run_outlook_signup_with_identity()` |
| `utils/cleanup.py` | **ENHANCED** | Graceful shutdown, process trees, monitoring |

---

## Migration Guide

### Running V3 Orchestrator

```bash
# Instead of:
python orchestrator.py --profiles p1 p2 p3 --concurrency 3

# Use:
python orchestrator_v3.py --profiles p1 p2 p3 --concurrency 3 --pool-size 5

# New options:
#   --pool-size N    Pre-generate N identities (default: 5)
#   --country CODE   Country for identity generation (default: US)
```

### Backward Compatibility

- `run.py` still works standalone (no changes)
- `orchestrator.py` still works (not modified)
- `outlook/run.py` → `run_outlook_signup()` still works unchanged
- All existing action modules work without modification

---

## Metrics to Monitor

| Metric | How to Get | Target |
|--------|-----------|--------|
| Identity pool size | `identity_pool.get_stats()` | Always > 0 |
| Launch latency | `metrics.launch_duration` | < 10s |
| Task duration | `metrics.task_duration` | < 300s |
| Error rate | `total_errors / total_profiles` | < 20% |
| Memory per profile | `get_resource_usage()` | < 120MB |
| Active browsers | `browser_processes` count | ≤ concurrency |
| Zombie processes | Post-cleanup check | 0 |

---

## Future Improvements (Phase 3+)

1. **Event-driven architecture**: Replace polling loops with event emitters
2. **Browser session pooling**: Reuse warm browser contexts across tasks
3. **Distributed workers**: Scale across multiple machines
4. **Dashboard**: Real-time monitoring via WebSocket
5. **Smart retry**: ML-based retry decisions based on error patterns
6. **Rate limiter**: Centralized AdsPower API rate limiting
