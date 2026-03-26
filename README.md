# Amazon Automation

Automated product browsing, account creation, and purchasing on Amazon using **AdsPower** browsers, **AgentQL** for robust element detection, and **Playwright** (via Patchright).

## Features

- **Anti-Detect Browsing**: Uses AdsPower fingerprints and residential proxies (Decodo).
- **Intelligent Automation**: Powered by AgentQL to find elements even when selectors change, with a tiered fallback chain (XPath cache → CSS → AgentQL → semantic roles).
- **Account Creation**: Automates Outlook email signup **or** signs in with pre-existing Outlook credentials from a local file.
- **Identity Pipeline**: Pre-generates realistic identities (name, DOB, password) in a warm pool before browser launch for faster execution.
- **WebAuthn / Passkey Bypass**: Automatically suppresses native passkey dialogs via CDP virtual authenticators — no manual intervention needed.
- **OpSec Workflow**: Includes cookie warm-up, human-like typing/scrolling, and randomised delays.
- **Multi-Profile Orchestration**: Run multiple profiles in parallel with configurable concurrency and automatic retry logic.
- **Automated Lifecycle**: Automatically handles profile creation, browser configuration, and **automated deletion** upon completion to keep your AdsPower account clean.
- **Identity Verification (IDV)**: Generates highly realistic, platform-consistent Driver's Licenses (front/back) with shared visual backgrounds for maximum realism.
- **Multi-Platform**: Supports Windows, macOS, Android, and iOS browser profiles.

## Prerequisites

- **Python 3.8+**
- **AdsPower Browser**: the application must be installed, running, and the Local API enabled in settings.
- **AgentQL API Key**: Get one from [AgentQL](https://agentql.com/).
- **Decodo Proxy Credentials**: Active subscription for residential proxies.

## Installation

1. **Clone the repository:**
    ```bash
    git clone https://github.com/eliasluimeme/autamazon
    cd autamazon
    ```

2. **Automated Setup & Activation:**
    The project includes an automated script that creates a virtual environment, handles all dependencies (including browsers), and activates it in your current terminal session.

    **On macOS / Linux:**
    ```bash
    source ./setup.sh
    ```

    **On Windows:**
    ```cmd
    .\setup.bat
    ```

## Configuration

1. **Environment Variables:**
    The setup script automatically creates a `.env` file from `.env.example`.

2. **Edit `.env`:**
    Open `.env` and fill in your credentials:
    - `DECODO_USERNAME` / `DECODO_PASSWORD` — Residential proxy provider details.
    - `AGENTQL_API_KEY` — Your AgentQL API key for intelligent element detection.
    - `ADSPOWER_API_URL` — Ensure this matches your AdsPower local API settings.

## Usage

### 1. Create Browser Profiles

Use `setup_profiles.py` to create new AdsPower profiles configured with proxies and fingerprints.

```bash
python setup_profiles.py --platform android --country au
```

This will:
- Generate a proxy config for the target country.
- Create a new browser profile in AdsPower with the specified OS type.
- Apply OS-specific fingerprint hardening.

### 2. Run Automation

**Single Profile:**
```bash
python run.py <PROFILE_ID>
```

**V3 Orchestrator (Multi-profile):**
```bash
# Create 2 new profiles and run them
python orchestrator_v3.py --accounts 2

# Run specific profiles in parallel
python orchestrator_v3.py --profiles id1 id2 id3 --concurrency 3

# Drop profiles that hit phone verification
python orchestrator_v3.py --accounts 5 --drop-on-phone

# Keep profiles for inspection (skip auto-deletion)
python orchestrator_v3.py --accounts 2 --skip-delete
```

### Orchestrator Arguments

| Argument | Default | Description |
|---|---|---|
| `--profiles` | — | One or more AdsPower profile IDs to run. |
| `--accounts` | — | Number of new profiles to create automatically (alternative to `--profiles`). |
| `--os` | `windows` | OS type for newly created profiles (`windows`, `mac`, `android`, `ios`). |
| `--concurrency` | `3` | Max profiles running in parallel. |
| `--pool-size` | `5` | Number of identities to pre-generate before any browser starts. |
| `--country` | `AU` | Country code for identity generation and proxy selection. |
| `--max-retries` | `3` | Max retry attempts per profile on failure. |
| `--skip-outlook-signup` | `False` | Skip Outlook account creation and sign in with an existing credential from `--emails-file` instead. |
| `--emails-file` | `emails/emails.txt` | Path to the credentials file used when `--skip-outlook-signup` is set. |
| `--drop-on-phone` | `False` | Automatically "drop" and stop execution for a profile if it hits an Amazon phone number verification prompt. |
| `--skip-delete` | `False` | Skip the automatic deletion of the AdsPower profile after completion (useful for debugging). |

### Outlook Sign-in Mode

When you have pre-existing Outlook / Hotmail accounts, pass `--skip-outlook-signup` to reuse them instead of creating new ones:

```bash
python orchestrator_v3.py --profiles id1 id2 --skip-outlook-signup
# Custom emails file
python orchestrator_v3.py --profiles id1 id2 --skip-outlook-signup --emails-file emails/my_accounts.txt
# With country-specific identity generation
python orchestrator_v3.py --profiles id1 id2 --skip-outlook-signup --country AU
```

**How it works:**

1. The orchestrator reads the next unused credential from `--emails-file`.
2. It opens the profile browser and logs in to Outlook with that email.
3. On success, a complete, realistic identity is generated via `IdentityGenerator` for the target `--country` — the sign-in email and password are injected into that identity so downstream phases receive coherent person data.
4. The consumed credential is immediately marked (`#USED:`) in the file before any browser opens, so concurrent workers can never claim the same address.

**Credentials file format** (`email:password`, one per line):

```
AliceSmith42@hotmail.com:Secr3tPass!
BobJones99@outlook.com:An0therP@ss
```

After consumption:

```
#USED:AliceSmith42@hotmail.com:Secr3tPass!
BobJones99@outlook.com:An0therP@ss
```

> The orchestrator exits with an error at startup if `--skip-outlook-signup` is used but no unused emails remain.

## Project Structure

```
├── orchestrator_v3.py       # Multi-profile parallel orchestrator (main entry point)
├── run.py                   # Single-profile automation entry point
├── setup_profiles.py        # AdsPower profile creation & configuration
├── config.py                # Global configuration constants
├── device_adapter.py        # Desktop / mobile input abstraction layer
├── identity_manager.py      # Identity data model
│
├── actions/                 # Amazon automation action handlers
│   ├── signup_flow.py       #   Account signup orchestration
│   ├── signin_email.py      #   Email-based sign-in
│   ├── product_search_flow.py # Product search & browse
│   ├── ebook_search_flow.py #   E-book search & purchase
│   ├── cart.py              #   Cart interactions
│   ├── passkey.py           #   Amazon passkey nudge handler
│   ├── puzzle_solver.py     #   CAPTCHA / puzzle solver
│   ├── developer_registration.py # Developer account setup
│   ├── identity_verification.py  # IDV flow
│   └── ...
│
├── outlook/                 # Outlook email signup module
│   ├── run.py               #   Signup flow orchestration
│   ├── config.py            #   Outlook-specific settings
│   ├── identity.py          #   Identity generation for Outlook
│   ├── actions/             #   Step handlers (email, password, DOB, CAPTCHA, passkey, etc.)
│   └── utils/               #   XPath cache, helpers
│
├── outlook_login/           # Outlook sign-in module (for pre-existing accounts)
│
├── core/                    # Core framework
│   ├── identity_pool.py     #   Pre-generation pool for identities
│   ├── profile_lifecycle.py #   Profile state machine (idle → launching → working → done)
│   ├── session.py           #   Session management
│   └── two_factor.py        #   2FA handling
│
├── modules/                 # Shared utility modules
│   ├── adspower.py          #   AdsPower API integration
│   ├── opsec_workflow.py    #   Browser lifecycle & OpSec phases
│   ├── proxy.py             #   Proxy configuration (Decodo)
│   ├── identity_generator.py #  Realistic identity generation
│   ├── persona_factory.py   #   Cohesive persona creation
│   ├── human_input.py       #   Human-like mouse & keyboard simulation
│   ├── cookie_generator.py  #   Natural browsing history generation
│   └── dl_factory.py        #   Driver's license template factory
│
├── utils/                   # Low-level utilities
│   ├── xpath_cache.py       #   XPath caching for fast element lookups
│   ├── human_type.py        #   Character-by-character typing
│   ├── imap_helper.py       #   IMAP email verification
│   └── mouse_random_click.py #  Randomised click coordinates
│
├── emails/                  # Pre-existing email credentials
├── data/                    # Identity data, sessions, DL templates
├── logs/                    # Per-profile execution logs
└── configs/                 # Template configurations (DL, etc.)
```

## Troubleshooting

- **AdsPower Error**: Ensure the AdsPower app is open and the Local API is enabled in settings.
- **AgentQL Error**: Check your API key in `.env`.
- **Proxy Error**: Verify your Decodo credentials and balance.
- **Passkey Loop**: The WebAuthn bypass should handle this automatically. If the browser still shows a native passkey dialog, ensure you're running the latest code.
- **Phone Verification Drop**: If profiles are being terminated unexpectedly, check if `--drop-on-phone` is enabled. This is intentional to avoid wasting resources on accounts that require manual mobile verification.
- **Profile Gone?**: By default, the script now deletes AdsPower profiles after a run to save space. Use `--skip-delete` if you need them to persist.

---
**Note**: This tool is for educational and testing purposes only.
