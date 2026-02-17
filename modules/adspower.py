import time
import requests
import random
from loguru import logger
from modules.config import ADSPOWER_API_URL

class AdsPowerProfileManager:
    """
    Implements the robust "Create -> Inspect (Live) -> Harden" workflow.
    """
    def __init__(self, api_url=ADSPOWER_API_URL):
        self.api_url = api_url

    def _api_request(self, endpoint, payload=None):
        try:
            url = f"{self.api_url}{endpoint}"
            if payload:
                resp = requests.post(url, json=payload, timeout=20)
            else:
                resp = requests.get(url, timeout=20)
            
            resp.raise_for_status()
            data = resp.json()
            
            if data["code"] != 0:
                logger.error(f"⚠️ API Error ({endpoint}): {data.get('msg')}")
                return None
            return data["data"]
        except Exception as e:
            logger.error(f"❌ Connection Failed: {e}")
            return None

    def create_random_profile(self, name=None, group_id="0", proxy_config=None, fingerprint_config=None):
        """Step 1: Create a profile with minimal config/random OS."""
        if not name:
            name = f"Auto_Random_{int(time.time())}"
            
        payload = {
            "name": name,
            "group_id": group_id,
            "user_proxy_config": proxy_config,
        }
        if fingerprint_config:
            payload["fingerprint_config"] = fingerprint_config

        data = self._api_request("/api/v2/browser-profile/create", payload)
        if data:
            logger.info(f"✅ Created Random Profile: {data['profile_id']} ({name})")
            return data["profile_id"]
        return None

    def start_profile(self, profile_id, headless=1, open_tabs=0):
        """Start profile using V1 endpoint."""
        try:
            url = f"{self.api_url}/api/v1/browser/start?user_id={profile_id}&headless={headless}&open_tabs={open_tabs}"
            resp = requests.get(url, timeout=30)
            try:
                data = resp.json()
            except ValueError:
                logger.error(f"Start Profile API returned non-JSON: {resp.text}")
                return None
                
            if data["code"] == 0:
                logger.success(f"🚀 Browser started for profile {profile_id}")
                return data["data"]
            else:
                logger.error(f"Failed to start profile: {data.get('msg')}")
        except Exception as e:
            logger.error(f"Start Profile Error: {e}")
        return None

    def stop_profile(self, profile_id):
        """Stop profile using V1 endpoint."""
        try:
            url = f"{self.api_url}/api/v1/browser/stop?user_id={profile_id}"
            requests.get(url, timeout=10)
        except Exception:
            pass

    def inspect_profile_live(self, user_id):
        """Step 2: Start browser and inspect via CDP."""
        logger.info(f"🕵️ Starting live inspection for {user_id}...")
        
        system = "Unknown"
        ua = None
        
        browser_info = self.start_profile(user_id, headless=1, open_tabs=0)
        if browser_info and "debug_port" in browser_info:
            try:
                port = browser_info["debug_port"]
                cdp_url = f"http://127.0.0.1:{port}/json/version"
                cdp_resp = requests.get(cdp_url, timeout=5)
                cdp_data = cdp_resp.json()
                ua = cdp_data.get("User-Agent")
                logger.info(f"🕵️ Retrieved UA via CDP: {ua}")
            except Exception as e:
                logger.error(f"CDP Inspection Failed: {e}")
            finally:
                self.stop_profile(user_id)
        else:
             logger.error("Could not start browser for inspection.")

        if ua:
            if "Macintosh" in ua or "Mac OS" in ua:
                system = "macOS"
            elif "Windows" in ua:
                system = "Windows"
            elif "Android" in ua:
                system = "Android"
            elif "iPhone" in ua or "iPad" in ua:
                system = "iOS"
            elif "Linux" in ua: 
                system = "Linux"

        return {"system": system, "user_agent": ua, "cdp_info": cdp_data if 'cdp_data' in locals() else {}}

    def generate_hardening_config(self, system):
        """Step 3: Generate config based on detected system."""
        # Universal Settings
        config = {
             "automatic_timezone": "1",
             "language_switch": "1",
             "webrtc": "forward",
             "scan_port_type": "1",
             "do_not_track": "false",
             "flash": "block",
             
             # Noise Settings
             "canvas": "1",
             "webgl_image": "1",
             "audio_context": "1",
             "client_rects": "1",
             "media_devices": "2",
             "fonts_type": "2"
        }

        # Hardware Specs based on OS
        if system == "Windows":
             config.update({"ram": "8", "cores": "16", "gpu": "0"})
        elif system == "macOS":
             config.update({"ram": "8", "cores": "12", "gpu": "0"})
        elif system == "Android":
             config.update({"ram": "8", "cores": "8"})
        elif system == "iOS":
             config.update({"ram": "4", "cores": "8"})
        else: # Linux/Unknown
             config.update({"ram": "8", "cores": "8"})
             
        return config

    def apply_hardening(self, profile_id, config, system=None):
        """Step 4: Update profile. Rename if system is known."""
        payload = {
            "profile_id": profile_id,
            "fingerprint_config": config
        }
        
        if system and system != "Unknown":
            new_name = f"Auto_{system}_{int(time.time())}"
            payload["name"] = new_name
            logger.info(f"✏️ Renaming to: {new_name}")

        res = self._api_request("/api/v2/browser-profile/update", payload)
        if res is not None:
            logger.success(f"🔒 Hardening Applied to {profile_id}")
            return True
        return False

    def update_profile(self, profile_id, name=None, user_agent=None, fingerprint_config=None):
        """Generic profile update."""
        payload = {"profile_id": profile_id}
        if name:
            payload["name"] = name
        if user_agent:
            payload["user_agent"] = user_agent
        if fingerprint_config:
            payload["fingerprint_config"] = fingerprint_config
            
        res = self._api_request("/api/v2/browser-profile/update", payload)
        if res is not None:
            logger.success(f"✏️ Profile Updated for {profile_id}")
            return True
        return False

    def update_profile_proxy(self, profile_id, proxy_config):
        """Update the proxy configuration for a specific profile."""
        payload = {
            "profile_id": profile_id,
            "user_proxy_config": proxy_config
        }
        
        res = self._api_request("/api/v2/browser-profile/update", payload)
        if res is not None:
            logger.success(f"🌍 Proxy Updated for {profile_id}")
            return True
        return False

    def delete_profile(self, profile_id):
        # Useful for cleanup
        endpoint = "/api/v2/browser-profile/delete"
        payload = {"profile_ids": [profile_id]}
        try:
            data = self._api_request(endpoint, payload)
            if data is not None:
                logger.info(f"🗑️ Deleted Profile {profile_id}")
                return True
        except Exception:
            pass
        return False
