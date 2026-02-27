# Advanced V2 Architecture: Production Ready Amazon Automation

## 1. Goal 
Transition the current procedural automation script into a scalable, fault-tolerant, modular system based on independent state machines. The system must support massive parallel executions, cross-profile reliability, centralized state management, and extreme optimization of UI interactions.

---

## 2. Structural Paradigm Shift: From Procedural to State Machines
Currently, `run.py` executes a rigid sequence: Launch -> Detect -> Outlook -> Amazon eBook -> Buy Now -> Signup -> Dev Reg -> 2FA. If any step throws an unexpected error or timeout, the entire session fails.

### V2 Approach: Independent Subprocess Modules
We will decouple each logical phase into isolated subprocesses. Each subprocess operates as its own **State Machine**.
- **Master Orchestrator**: Decides *which* subprocess to run based on a persisted status flag.
- **Subprocess Loop**: Uses a specialized `detect_state()` function to determine the exact screen.
- **Routing**: Matches the detected state to a handler, executing the required interactions.
- **Recovery & Retries**: If `element not found` occurs, the loop repeats, re-detects the state, and retries. If stuck in an error loop, the Subprocess resets its entry URL and tries again securely.

### Benefits
- Code becomes infinitely more testable (you can test just the Dev Registration independently).
- Retries become organic; instead of complex `try/except` nesting, the loop handles it.
- Execution can automatically resume exactly where it failed on a previous run.

---

## 3. The `InteractionEngine`: Speed & Efficiency
To optimize the script and decrease reliance on heavy AgentQL calls while maintaining Human-like anti-bot protections, we must formalize an Interaction wrapper.

### Interaction Strategy Priorities:
1. **Cache Primary**: Always attempt `get_cached_xpath()` first.
2. **Standard Selectors**: Try highly-specific CSS/XPaths (Text-based).
3. **AgentQL Fallback**: If standard methods fail, query AgentQL. On success, auto-extract the XPath and cache it to eliminate future queries for that selector profile.

### Execution Tiering (The Waterfall Click Method):
For elements that don't absolutely require bio-mechanical proof (like standard navigations) vs. sensitive ones (like "Buy Now" or "Create Account"):
- **Tier 1 (Efficiency)**: `device.js_click(element)` - The fastest. Executes a JS click in the DOM hierarchy. Used for non-sensitive data inputs/dropdowns.
- **Tier 2 (Synthetic)**: `element.dispatch_event('click')` - Fast native browser event.
- **Tier 3 (Biomechanical Override)**: `human_like_mobile_tap()` or `human_like_mouse_click()` - Simulates physical touches with bounding box offsets, curve scrolling, and pressure physics. Reserved for high-risk funnel buttons.

---

## 4. Robust Device Adaptability
The existing `DeviceAdapter` is highly modular (`device_adapter.py`). 
To ensure seamless execution on both Desktop and Mobile configurations via AdsPower:
- **Typing Framework**: Automatically map to `human_like_type` (Desktop) vs `human_like_mobile_type` (Mobile).
- **Click Mapping**: Automatically route Tier 3 clicks to CDP Touch Events for Mobile platforms and raw Mouse APIs for Desktop. 
- **Viewports & Interstitials**: Popups (cookies, app banners) vary by device. We will centralize interstitial handling that dynamically checks device layout dimensions.

---

## 5. Standardized Error Handling
- Remove scattered `time.sleep()` in favor of Playwright's native `wait_for` loops combined with our custom State Machine. 
- Use exponential back-offs when element timeouts occur.
- Categorize errors:
    - **Fatal**: IP banned, Account Locked -> Marks Profile as FAILED/BANNED, closes browser.
    - **Recoverable**: Element missed, page blank -> Triggers a page reload and state re-detection.
    - **Manual Intervention**: 2FA App bind -> Triggers a pause on the worker loop and sends an external notification.
