# Data Flow and Parallel Orchestration Plan

## 1. Centralized State Storage (`SessionState`)
Currently, data such as the parsed `Identity` objects and runtime flags are passed through python variables procedurally. If the script crashes, data is lost.

### Implementation:
We will create a `core/session.py` layer that interfaces with a local JSON store (or SQLite) indexed by `PROFILE_ID`.

**Structure:**
```json
{
    "profile_id": "k18imh7u",
    "status": "PROCESSING",
    "platform": "mobile",
    "completion_flags": {
        "outlook_created": true,
        "amazon_signup": false,
        "dev_registration": false,
        "2fa_enabled": false
    },
    "identity": {
        "email": "user@outlook.com",
        "password": "pwd",
        "two_fa_secret": null
    }
}
```
**Data Flow:**
1. Orchestrator reads target profiles.
2. `run.py` initializes by loading the `SessionState`.
3. The script skips modules where `completion_flags` are `true`.
4. The `IdentityManager` interacts directly with this session object, updating passwords or 2FA secrets synchronously.

---

## 2. Parallel Orchestration Engine
Generating multiple profiles simultaneously requires a higher-level orchestrator script that spins up multiple isolated browser/python processes without bleeding data.

### 2.1 The `orchestrator.py` Service
A new root-level file that utilizes Python's `asyncio` or `ProcessPoolExecutor` to manage a queue of Jobs.
- **Queue Source**: Retrieves profile IDs from a database, file, or API.
- **Concurrency Control**: A semaphore mechanism to limit max concurrent browsers (e.g., maximum 5 threads) to prevent CPU/RAM overwhelming.
- **Subprocess Execution**: It launches `run.py <PROFILE_ID>` as a detached sub-process. 
- **Process Monitoring**: Captures `stdout/stderr` uniquely for each profile, piping them to isolated log files (e.g., `logs/k18imh7u.log`) rather than mixing terminal outputs.

### 2.2 Shared Resource Contention Management
- **XPath Cache**: The `.selector_cache.json` must implement a file lock (`filelock` library) so parallel processes don't corrupt the JSON when writing new cached selectors simultaneously.
- **AdsPower API Limits**: AdsPower local API can bottleneck. The orchestrator batches Start/Stop requests or introduces jitter/delays between browser launches.
- **Network Logging**: Proxy and network resources are heavy. Parallel bots must log telemetry cleanly to the global dashboard without collision.

### 2.3 Subprocess Isolation
Each parallel run operates securely because:
- The AdsPower Context is completely separate.
- The `SessionState` operates on independent file configurations per-profile.
- Playwright instances run within their own worker space.
