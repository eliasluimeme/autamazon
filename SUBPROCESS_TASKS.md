# Detailed Subprocess Refactoring Tasks

Detailed checklist to transition to V2 of the Amazon Automation architecture.

## Phase 1: Foundation & Core Updates
- [x] **Task 1: Build `core/session.py`**. 
  - Migrate away from passing `Identity` in memory.
  - Implement read/write from local JSON per profile.
- [x] **Task 2: Build `InteractionEngine` Wrapper**.
  - Centralize `js_click`, `dispatch_event`, and `mobile_touch`/`mouse_click`.
  - Bake AgentQL fallback natively into this wrapper.
- [x] **Task 3: Refactor XPath Cache**. 
  - Add thread-safe `FileLock` to `xpath_cache.py` to prevent corruption during parallel runs.

## Phase 2: Refactoring Amazon Navigation & Cart Subprocess
*Target `actions/ebook_search_flow.py`*
- [x] **Task 4: State Machine Conversion**.
  - Remove long procedural waits. Add `detect_cart_state(page)` scanning for: `storefront`, `product_list`, `product_page`, `cart_confirm`, `login_prompt`.
- [x] **Task 5: Element Selection Polish**.
  - Route the massive "Buy Now 1-Click" finder through the new `InteractionEngine`. It should check Cache -> Selectors -> AgentQL, and use JS Click natively unless specified otherwise.

## Phase 3: Unified Signup Flow Optimization
*Target `actions/signup_flow.py`*
- [x] **Task 6: Pure Function Parameters**.
  - Re-read all Identity data from `SessionState`.
- [x] **Task 7: Optimize Email OTP Retrieval**. 
  - Currently opens `outlook.live.com` in a new tab via Playwright. 
  - **Improvement**: Implement a backend IMAP script (`imaplib`) for fetching emails silently via python using the Outlook identity. This is 100x faster, less prone to UI breakage, and avoids interacting with DOM entirely.
  - *Fallback*: If IMAP is blocked, isolate the Playwright mailbox tab handling logic significantly.
- [x] **Task 8: Standardize Captcha Retry Logic**.
  - Ensure loops trigger re-loads gracefully if Captchas fail multiple times.

## Phase 4: Developer Registration Enhancements
*Target `actions/developer_registration.py`*
- [x] **Task 9: Fix React Dropdown Automation**.
  - The fire-and-forget country/phone dropdowns are brittle. Build an explicit JS evaluation hook that interacts directly with React fiber nodes or natively triggers input React changes if UI clicks glitch out.
- [x] **Task 10: State Integration**.
  - Incorporate into the standard `detect_dev_state` loop so failure mid-form forces a clean refresh instead of failing completely.

## Phase 5: 2FA / Authentication Overhaul
*Target `actions/two_step_verification.py`*
- [x] **Task 11: Phase Out `2fa.zone`**.
  - Current script opens a new browser tab to `2fa.zone` to generate TOTP codes.
  - **Improvement**: Replace with `pyotp` library. Store the Base32 secret in the `SessionState` and generate codes locally. This is faster and removes an external dependency.
- [x] **Task 12: Robust Identify Matching on Re-Auth**.
  - In `handle_login_prompt`, ensure the password selected is double-checked against the email currently on the Amazon screen (if visible) from the identity pool, allowing the script to recover if it somehow uses a different account.

## Phase 6: Parallel Orchestration
  - Creates isolated log streams per profile.
- [ ] **Task 14: Monitor Dashboard Sync**
  - Make sure successes/fails update a global database or tracking file for the user interface.
