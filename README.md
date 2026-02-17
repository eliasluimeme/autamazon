# Amazon Automation

Automated product browsing, account creation, and purchasing on Amazon using **AdsPower** browsers, **AgentQL** for robust element detection, and **Playwright**.

## Features

- **Anti-Detect Browsing**: Uses AdsPower fingerprints and residential proxies (Decodo).
- **Intelligent Automation**: Powered by AgentQL to find elements even when selectors change.
- **Account Creation**: Automates Outlook email creation and Amazon account signup.
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
    cd amazon-automation
    ```

2.  **Create and activate a virtual environment:**
    ```bash
    python -m venv .venv
    source .venv/bin/activate  # On Windows: .venv\Scripts\activate
    ```

3.  **Install dependencies:**
    ```bash
    pip install -r requirements.txt
    ```

4.  **Install Playwright browsers:**
    ```bash
    playwright install
    ```

## Configuration

1.  **Set up environment variables:**
    Copy the example configuration file to create your local settings.
    ```bash
    cp .env.example .env
    ```

2.  **Edit `.env`:**
    Open `.env` in your text editor and fill in your credentials:
    - `DECODO_USERNAME` / `DECODO_PASSWORD`: Your proxy provider details.
    - `AGENTQL_API_KEY`: Your AgentQL API key.
    - `ADSPOWER_API_URL`: Ensure this matches your AdsPower local API settings (default is usually correct).

## Usage

### 1. Setup Browser Profile
Use `setup.py` to create a new AdsPower profile configured with a proxy and your settings.

```bash
python setup.py
```
This will:
- Generate a proxy config for the target country.
- Create a new Android/iOS/Desktop profile in AdsPower.
- Apply OS-specific hardening.
- Open the browser.

### 2. Run Automation
Once the profile is created, you can run the main automation script using the **Profile ID** (printed by the setup script or visible in AdsPower).

```bash
# Basic usage
python run.py <PROFILE_ID>

# Search for a specific product
python run.py <PROFILE_ID> --product "wireless headphones"
```

## Project Structure

- `run.py`: Main entry point for the automation.
- `setup.py`: Script to create and configure AdsPower profiles.
- `amazon/`: Core automation logic (actions, element locators).
- `modules/`: Helper modules for AdsPower, Proxy, and OpSec.
- `logs/`: Execution logs.

## Troubleshooting

- **AdsPower Error**: Ensure the AdsPower app is open and the Local API is enabled in settings.
- **AgentQL Error**: Check your API key in `.env`.
- **Proxy Error**: Verify your Decodo credentials and balance.

---
**Note**: This tool is for educational and testing purposes only.
