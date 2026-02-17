import os
import json
import requests
from datetime import datetime
from loguru import logger

def get_proxy_ip_info(proxy_config: dict) -> dict | None:
    """
    Fetches IP information by making a request through the proxy.
    Uses 'https://ip.decodo.com/json' (or fallback) to get details.
    """
    if not proxy_config:
        return None
    
    try:
        # Construct proxy string for requests (Legacy Method)
        # http://user:pass@host:port
        proxy_url = f"http://{proxy_config['proxy_user']}:{proxy_config['proxy_password']}@{proxy_config['proxy_host']}:{proxy_config['proxy_port']}"
        proxies = {
            "http": proxy_url,
            "https": proxy_url
        }

        # logger.info("Checking proxy IP details...")
        response = requests.get("https://ip.decodo.com/json", proxies=proxies, timeout=10)
        response.raise_for_status()
        return response.json()

        # logger.info("Checking proxy IP details...")
        response = requests.get("https://ip.decodo.com/json", proxies=proxies, timeout=10)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        logger.warning(f"Failed to fetch proxy IP info: {e}")
        return None

def log_run_details(profile_id: str, proxy_config: dict, profile_data: dict, system: str, cdp_info: dict = None) -> str:
    """
    Logs the details of the current run to a JSON file.
    Appends to logs/runs/run_{DD-MM-YYYY}.json
    """
    try:
        # Check Proxy IP
        ip_info = get_proxy_ip_info(proxy_config)
        
        timestamp = datetime.now()
        log_dir = "logs/runs"
        os.makedirs(log_dir, exist_ok=True)
        
        filename = f"{log_dir}/run_{timestamp.strftime('%d-%m-%Y')}.json"
        
        # Extract country from proxy config for legacy compatibility
        country_code = "unknown"
        if proxy_config and "proxy_user" in proxy_config:
             parts = proxy_config["proxy_user"].split("-")
             if "country" in parts:
                 try:
                     idx = parts.index("country")
                     country_code = parts[idx + 1]
                 except (ValueError, IndexError):
                     pass

        # Extract details
        active_proxy = profile_data.get("user_proxy_config") if profile_data else None
        fingerprint = profile_data.get("fingerprint_config") if profile_data else None

        # Prepare Log Entry (Matching Legacy Structure + New CDP Info)
        entry = {
            "timestamp": timestamp.isoformat(),
            "profile_number": profile_id, # Legacy name
            "profile_id": profile_id,     # Also keep clear ID
            "country": country_code,
            
            # Proxy Details
            "input_proxy_config": proxy_config,
            "active_proxy_config": active_proxy,
            "proxy_ip_info": ip_info,
            
            # Browser Details
            "browser_fingerprint": fingerprint,
            "browser_cdp_info": cdp_info, # New Request
            "detected_system": system,
            
            # Full Dump
            "full_profile_details": profile_data,
            
            # Run Meta
            "run_id": f"run_{int(timestamp.timestamp())}",
        }
        
        # Load or Init File
        current_data = []
        if os.path.exists(filename):
            try:
                with open(filename, "r", encoding="utf-8") as f:
                    content = f.read()
                    if content.strip():
                        current_data = json.loads(content)
            except Exception:
                current_data = []
        
        current_data.append(entry)
        
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(current_data, f, indent=4, ensure_ascii=False)
            
        logger.success(f"📝 Run details logged to {filename}")
        return filename
        
    except Exception as e:
        logger.error(f"❌ Failed to log run details: {e}")
        return None
