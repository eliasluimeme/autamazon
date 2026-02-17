import os
import sys
from datetime import datetime
from dotenv import load_dotenv
from loguru import logger

# Load environment variables
# env_path = os.path.join(os.path.dirname(__file__), "../testcase/.env")
load_dotenv()

# AdsPower Settings
ADSPOWER_API_URL = os.getenv("ADSPOWER_API_URL", "http://local.adspower.net:50325").rstrip('/')

# Proxy Settings
DECODO_PROXY_HOST = os.getenv("DECODO_PROXY_HOST", "gate.decodo.com")
DECODO_PROXY_PORT = os.getenv("DECODO_PROXY_PORT", "7000")
DECODO_USERNAME = os.getenv("DECODO_USERNAME")
DECODO_PASSWORD = os.getenv("DECODO_PASSWORD")

# Proxy Logic Settings
TARGET_COUNTRY = os.getenv("TARGET_COUNTRY", "be").lower()
RANDOM_COUNTRY_MODE = os.getenv("RANDOM_COUNTRY_MODE", "false").lower() == "true"
PROXY_SESSION_DURATION = int(os.getenv("PROXY_SESSION_DURATION", "60"))

# OpSec Workflow Settings
ENABLE_OPSEC_WORKFLOW = os.getenv("ENABLE_OPSEC_WORKFLOW", "true").lower() == "true"
TARGET_URL = os.getenv("TARGET_URL", "https://06bdmbet07.com")
WARMUP_DURATION = int(os.getenv("WARMUP_DURATION", "3"))

# Logging Setup
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

logger.remove()

logger.add(
    sys.stdout,
    level=LOG_LEVEL,
    format="<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | <level>{level: <8}</level> | <cyan>{module}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>"
)

# Ensure logs directory exists at project root or relative
os.makedirs("logs", exist_ok=True)
logger.add(f"logs/{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.log", level=LOG_LEVEL, rotation="10 MB")
