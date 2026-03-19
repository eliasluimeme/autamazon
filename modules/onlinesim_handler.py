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
            if data.get("response") == 1:
                balance = data.get("balance")
                logger.info(f"💰 OnlineSim Balance: {balance}")
                return balance
        except Exception as e:
            logger.warning(f"Failed to fetch OnlineSim balance: {e}")
        return None

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
            
            # The API returns either a list of countries or a single country object if country param is passed
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

    def get_sms(self, tzid, timeout=None):
        """
        Poll for SMS OTP.
        Returns the OTP code if found.
        """
        timeout = timeout or config.ONLINESIM_SMS_TIMEOUT
        poll_interval = config.ONLINESIM_POLL_INTERVAL
        url = f"{self.base_url}/rent/getRentState.php"
        params = {
            "apikey": self.api_key,
            "tzid": tzid
        }
        
        start_time = time.time()
        logger.info(f"⏳ Waiting for SMS for tzid {tzid} (timeout: {timeout}s)...")
        
        while time.time() - start_time < timeout:
            try:
                response = requests.get(url, params=params)
                data = response.json()
                
                if data.get("response") == 1:
                    list_items = data.get("list", [])
                    for item in list_items:
                        # Find our transaction
                        if str(item.get("tzid")) == str(tzid):
                            messages = item.get("messages", [])
                            if messages:
                                # Get latest message
                                last_msg = messages[-1]
                                msg_text = last_msg.get("text", "")
                                code = last_msg.get("code")
                                
                                logger.info(f"Message received: '{msg_text}'")
                                
                                # If code is not explicitly provided, try to extract it (usually 6 digits)
                                if not code:
                                    match = re.search(r'\b(\d{6})\b', msg_text)
                                    if match:
                                        code = match.group(1)
                                
                                if code:
                                    logger.info(f"✅ Found SMS code: {code}")
                                    return code
                else:
                    error_msg = data.get("response")
                    if error_msg == "NO_NUMBER":
                        logger.error(f"❌ Transaction {tzid} not found or expired")
                        return None
                    
            except Exception as e:
                logger.warning(f"Error polling SMS: {e}")
            
            time.sleep(poll_interval)
            
        logger.warning(f"⏰ Timeout waiting for SMS for tzid {tzid}")
        return None

    def close_number(self, tzid):
        """
        Release/Close the rented number.
        """
        if not tzid:
            return False
            
        url = f"{self.base_url}/rent/closeRentNum.php"
        params = {
            "apikey": self.api_key,
            "tzid": tzid
        }
        
        try:
            response = requests.get(url, params=params)
            data = response.json()
            # API might return True, 1, or {"response": 1}
            resp_val = data.get("response") if isinstance(data, dict) else data
            if resp_val is True or resp_val == 1 or resp_val == "1":
                logger.info(f"✅ Successfully closed number for tzid {tzid}")
                return True
            else:
                logger.warning(f"⚠️ Failed to close number for tzid {tzid}: {data}")
                return False
        except Exception as e:
            logger.exception(f"Error closing number: {e}")
            return False
