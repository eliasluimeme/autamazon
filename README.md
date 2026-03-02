# Amazon Automation

Automated product browsing, account creation, and purchasing on Amazon using **AdsPower** browsers, **AgentQL** for robust element detection, and **Playwright**.

## Features

- **Anti-Detect Browsing**: Uses AdsPower fingerprints and residential proxies (Decodo).
- **Intelligent Automation**: Powered by AgentQL to find elements even when selectors change.
- **Account Creation**: Automates Outlook email *signup* **or** signs in with pre-existing Outlook credentials from a local file.
- **OpSec Workflow**: Includes warm-up phases and human-like interactions.
- **Multi-Platform**: Supports mobile and desktop emulation.

## Prerequisites

Before running this project, ensure you have the following:

- **Python 3.8+**
- **AdsPower Browser**: the application must be installed and running.
- **AgentQL API Key**: Get one from [AgentQL](https://agentql.com/).
- **Decodo Proxy Credentials**: Active subscription for residential proxies.

## Installation

1.  **Clone the repository:**
    ```bash
    git clone https://github.com/eliasluimeme/autamazon
    cd autamazon
    ```

2.  **Automated Setup & Activation:**
    The project includes an automated script that creates a virtual environment, handles all dependencies (including browsers), and activates it in your current terminal session.

    **On macOS / Linux / iOS (Development):**
    ```bash
    source ./setup.sh
    ```

    **On Windows:**
    ```cmd
    .\setup.bat
    ```

## Configuration

1.  **Environment Variables:**
    The setup script automatically creates a `.env` file from `.env.example`. 
    
2.  **Edit `.env`:**
    Open `.env` in your text editor and fill in your credentials:
    - `DECODO_USERNAME` / `DECODO_PASSWORD`: Your residential proxy provider details.
    - `AGENTQL_API_KEY`: Your AgentQL API key for intelligent element detection.
    - `ADSPOWER_API_URL`: Ensure this matches your AdsPower local API settings.

## Usage

### 1. Setup Browser Profile
Use `setup.py` to create a new AdsPower profile configured with a proxy and your settings.

```bash
python setup_profiles.py --platform android --country au
```
This script will:
- Generate a proxy config for the target country.
- Create a new Android/iOS/Desktop profile in AdsPower.
- Apply OS-specific "hardening" (patching fingerprints).
- Open the browser automatically.

### 2. Run Automation
You can run the main automation script using the **Profile ID** or use the V3 Orchestrator for multiple profiles.

**Single Profile:**
```bash
python run.py <PROFILE_ID>
```

**V3 Orchestrator (Multi-profile):**
```bash
python orchestrator_v3.py --profiles id1 id2 id3 --concurrency 3
```

#### Orchestrator Arguments

| Argument | Default | Description |
|---|---|---|
| `--profiles` | — | One or more AdsPower profile IDs to run. |
| `--accounts` | — | Number of new profiles to create automatically (alternative to `--profiles`). |
| `--os` | `windows` | OS type for newly created profiles (`windows`, `mac`, `android`, `ios`). |
| `--concurrency` | `3` | Max profiles running in parallel. |
| `--pool-size` | `5` | Number of identities to pre-generate before any browser starts. |
| `--country` | `US` | Country code for identity generation and proxy selection. |
| `--max-retries` | `3` | Max retry attempts per profile on failure. |
| `--skip-outlook-signup` | `False` | **Skip** Outlook account creation and sign in with an existing credential from `--emails-file` instead. Each email is marked `#USED:` after consumption. |
| `--emails-file` | `emails/emails.txt` | Path to the credentials file used when `--skip-outlook-signup` is set. |

#### Outlook Sign-in Mode

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
3. On success, a **complete, realistic identity** is generated via `IdentityGenerator` for the target `--country` — the email address itself is never used as a name. The sign-in email and password are then injected into that identity, so downstream phases (Amazon signup, developer registration, IDV) all receive coherent person data.
4. The consumed credential is **immediately marked** in the file before any browser opens, so concurrent workers can never claim the same address.

**Credentials file format** (`email:password`, one per line):

```
AliceSmith42@hotmail.com:Secr3tPass!
BobJones99@outlook.com:An0therP@ss
```

After an email is consumed it is **automatically rewritten** with a `#USED:` prefix:

```
#USED:AliceSmith42@hotmail.com:Secr3tPass!
BobJones99@outlook.com:An0therP@ss
```

> The orchestrator exits with an error at startup if `--skip-outlook-signup` is used but no unused emails remain.

## Project Structure

- `run.py`: Main entry point for single-profile automation.
- `orchestrator_v3.py`: Main entry point for parallel/multi-profile automation.
- `setup.py`: Core project environment installation script.
- `setup_profiles.py`: Script to create and configure AdsPower profiles.
- `amazon/`: Core automation logic (actions, element locators).
- `modules/`: Helper modules for AdsPower, Proxy, and OpSec.
- `logs/`: Execution logs.

## Troubleshooting

- **AdsPower Error**: Ensure the AdsPower app is open and the Local API is enabled in settings.
- **AgentQL Error**: Check your API key in `.env`.
- **Proxy Error**: Verify your Decodo credentials and balance.

---
**Note**: This tool is for educational and testing purposes only.
