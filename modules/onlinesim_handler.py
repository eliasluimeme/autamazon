import requests
import time
import re
from loguru import logger
import config

class OnlineSimHandler:
    def __init__(self, api_key=None):
        self.api_key = api_key or config.ONLINESIM_API_KEY
        self.base_url = "https://onlinesim.io/api"
        
        if not self.api_key:
            logger.error("❌ ONLINESIM_API_KEY is not set in environment or config.")

    def get_balance(self):
        """Fetch the current balance from OnlineSim."""
        url = f"{self.base_url}/getBalance.php"
        params = {"apikey": self.api_key}
        try:
            response = requests.get(url, params=params)
            data = response.json()
            # Response field returns 1 if successful
            if str(data.get("response")) == "1":
                balance = data.get("balance")
                logger.info(f"💰 OnlineSim Balance: {balance}")
                return float(balance)
        except Exception as e:
            logger.warning(f"Failed to fetch OnlineSim balance: {e}")
        return None

    def get_number(self, country=None, service="amazon"):
        """
        Get a one-off number for a single service (activation).
        Returns (tzid, number)
        """
        country = country or config.ONLINESIM_DEFAULT_COUNTRY
        url = f"{self.base_url}/getNum.php"
        params = {
            "apikey": self.api_key,
            "country": country,
            "service": service
        }
        
        try:
            logger.info(f"Requesting activation number for {service} in country {country}...")
            response = requests.get(url, params=params)
            data = response.json()
            
            if str(data.get("response")) == "1":
                tzid = data.get("tzid")
                logger.info(f"Activation requested, tzid: {tzid}. Waiting for number...")
                
                # Poll getState until number is assigned
                for _ in range(10):
                    time.sleep(2)
                    state_url = f"{self.base_url}/getState.php"
                    state_resp = requests.get(state_url, params={"apikey": self.api_key, "tzid": tzid})
                    state_data = state_resp.json()
                    
                    # getState can return a list or a single object
                    operations = state_data if isinstance(state_data, list) else [state_data]
                    for op in operations:
                        if str(op.get("tzid")) == str(tzid):
                            number = op.get("number")
                            if number:
                                logger.info(f"✅ Received number: {number}")
                                return tzid, number
                            
                logger.warning(f"Timeout waiting for number assignment for tzid {tzid}")
                return tzid, None 
            else:
                error_msg = data.get("response")
                logger.error(f"❌ Failed to get activation number: {error_msg}")
                return None, None
        except Exception as e:
            logger.exception(f"Error getting activation number: {e}")
            return None, None

    def rent_number(self, country=None, days=None):
        """
        Rent a number for SMS receiving.
        Automatically finds the minimum allowed days for the country.
        Returns (tzid, number)
        """
        country = country or config.ONLINESIM_DEFAULT_COUNTRY
        
        # If days not specified, find the minimum allowed for this country
        if days is None:
            days = self._get_min_rent_days(country)
            
        url = f"{self.base_url}/rent/getRentNum.php"
        params = {
            "apikey": self.api_key,
            "country": country,
            "days": days
        }
        
        try:
            logger.info(f"Rent request to OnlineSim for country {country} ({days} days)...")
            response = requests.get(url, params=params)
            data = response.json()
            
            # Response is 1 if successful, or error message string
            if data.get("response") == 1:
                item = data.get("item", {})
                tzid = item.get("tzid")
                number = item.get("number")
                logger.info(f"✅ Rented number: {number} (tzid: {tzid})")
                return tzid, number
            else:
                error_msg = data.get("response")
                logger.error(f"❌ Failed to rent number: {error_msg}")
                # Log extra info if UNDEFINED_DAYS to help debugging
                if error_msg == "UNDEFINED_DAYS":
                    logger.debug(f"Target country {country} rejected days={days}. Checking tariffs might be needed.")
                return None, None
        except Exception as e:
            logger.exception(f"Error renting number: {e}")
            return None, None

    def _get_min_rent_days(self, country):
        """Fetch tariffs for the country and return the minimum available rental period."""
        url = f"{self.base_url}/rent/tariffsRent.php"
        params = {"apikey": self.api_key, "country": country}
        try:
            logger.debug(f"Fetching rent tariffs for country {country}...")
            response = requests.get(url, params=params)
            data = response.json()
            
            # If country param passed, it returns the object for that country
            if str(data.get("code")) == str(country) or str(data.get("position")) == str(country):
                days_dict = data.get("days", {})
                if days_dict:
                    # Extract numeric keys and sort
                    available = sorted([int(k) for k in days_dict.keys()])
                    min_days = available[0]
                    logger.debug(f"Min rental days for {country}: {min_days}")
                    return min_days
        except Exception as e:
            logger.warning(f"Could not determine min rent days for {country}: {e}")
            
        return 7 # Default fallback for most countries

    def get_sms(self, tzid, is_rent=False, timeout=None):
        """
        Poll for SMS OTP. Supports both Rent and Activation (Single service).
        is_rent=True uses getRentState, is_rent=False uses getState.
        Returns (code, number)
        """
        timeout = timeout or config.ONLINESIM_SMS_TIMEOUT
        poll_interval = config.ONLINESIM_POLL_INTERVAL
        
        url = f"{self.base_url}/rent/getRentState.php" if is_rent else f"{self.base_url}/getState.php"
        params = {
            "apikey": self.api_key,
            "tzid": tzid
        }
        
        start_time = time.time()
        logger.info(f"⏳ Waiting for {'Rent' if is_rent else 'Activation'} SMS for tzid {tzid} (timeout: {timeout}s)...")
        
        number = None
        
        while time.time() - start_time < timeout:
            try:
                response = requests.get(url, params=params)
                data = response.json()
                
                # Activation response pattern
                if not is_rent:
                    # getState returns a list of operations
                    operations = data if isinstance(data, list) else [data]
                    for op in operations:
                        if str(op.get("tzid")) == str(tzid):
                            # The number might finally appear here if not in getNum
                            if op.get("number") and not number:
                                number = op.get("number")
                                logger.info(f"📍 Activation number ready: {number}")
                            
                            msg_text = op.get("msg", "")
                            if msg_text:
                                logger.info(f"Message received: '{msg_text}'")
                                code = self._extract_code(msg_text)
                                if code:
                                    logger.info(f"✅ Found SMS code: {code}")
                                    return code, number
                            
                            # If no message yet, check response status
                            resp_status = op.get("response")
                            if resp_status == "TZ_NUM_WAIT":
                                pass # Still waiting
                            elif resp_status == "TZ_NUM_INVALID":
                                logger.error(f"❌ Transaction {tzid} invalid")
                                return None, number
                                
                # Rent response pattern
                else:
                    if data.get("response") == 1:
                        list_items = data.get("list", [])
                        for item in list_items:
                            if str(item.get("tzid")) == str(tzid):
                                messages = item.get("messages", [])
                                if messages:
                                    last_msg = messages[-1]
                                    msg_text = last_msg.get("text", "")
                                    logger.info(f"Message received: '{msg_text}'")
                                    code = last_msg.get("code") or self._extract_code(msg_text)
                                    if code:
                                        logger.info(f"✅ Found SMS code: {code}")
                                        return code, item.get("number")
                    elif data.get("response") == "NO_NUMBER":
                        logger.error(f"❌ Rent transaction {tzid} not found or expired")
                        return None, None
                    
            except Exception as e:
                logger.warning(f"Error polling SMS: {e}")
            
            time.sleep(poll_interval)
            
        logger.warning(f"⏰ Timeout waiting for SMS for tzid {tzid}")
        return None, number

    def _extract_code(self, text):
        """Helper to extract 6-digit code from text."""
        match = re.search(r'\b(\d{6})\b', text)
        return match.group(1) if match else None

    def close_number(self, tzid, is_rent=False):
        """
        Release/Close the rented or activated number.
        """
        if not tzid:
            return False
            
        url = f"{self.base_url}/rent/closeRentNum.php" if is_rent else f"{self.base_url}/setOperationOk.php"
        params = {
            "apikey": self.api_key,
            "tzid": tzid
        }
        
        try:
            response = requests.get(url, params=params)
            data = response.json()
            # API might return True, 1, or {"response": 1}
            resp_val = data.get("response") if isinstance(data, dict) else data
            if resp_val is True or resp_val == 1 or resp_val == "1" or resp_val == "OK":
                logger.info(f"✅ Successfully closed {'rent' if is_rent else 'activation'} for tzid {tzid}")
                return True
            else:
                logger.warning(f"⚠️ Failed to close tzid {tzid}: {data}")
                return False
        except Exception as e:
            logger.exception(f"Error closing number: {e}")
            return False
