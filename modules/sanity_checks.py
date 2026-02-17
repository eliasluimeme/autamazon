"""
OpSec Sanity Checks Module

Implements three critical validation functions to detect automation leaks
and ensure consistency before visiting target sites.
"""

import json
from loguru import logger


class SanityCheckException(Exception):
    """Raised when a critical sanity check fails."""
    pass


def check_automation_flags(page):
    """
    Check 1: The "Kill Switch" - Detects WebDriver & CDP Leaks
    
    Verifies that patchright and AdsPower successfully hid automation flags.
    
    Args:
        page: Patchright page object
        
    Raises:
        SanityCheckException: If any automation flag is detected
    """
    logger.info("🔍 Running Automation Flags Check...")
    
    risk_report = page.evaluate("""() => {
        return {
            // 1. The Classic WebDriver Flag
            webdriver: navigator.webdriver,
            
            // 2. CDP Runtime Side-Effects
            // CDC_ is a common prefix left by Selenium/Puppeteer
            cdc_detected: Object.keys(window).some(key => key.match(/^cdc_/i)),
            
            // 3. Permissions Leak (Bots often have inconsistent permission states)
            // Notification permission usually 'default' or 'denied', rarely 'granted' on fresh profile
            permissions: Notification.permission
        }
    }""")
    
    # Validate WebDriver flag
    if risk_report.get('webdriver'):
        raise SanityCheckException("🚨 FATAL: navigator.webdriver is TRUE. Immediate Abort.")
    
    # Validate CDC variables    
    if risk_report.get('cdc_detected'):
        raise SanityCheckException("🚨 FATAL: CDC_ variables detected (Automation Leak).")
    
    logger.success("✅ Automation Flags: Clean")
    logger.debug(f"   - navigator.webdriver: {risk_report.get('webdriver')}")
    logger.debug(f"   - CDC variables: {risk_report.get('cdc_detected')}")
    logger.debug(f"   - Notification permission: {risk_report.get('permissions')}")
    
    return risk_report


def check_network_consistency(page, expected_country_code):
    """
    Check 2: The "Mismatch" Check - Proxy vs. Timezone vs. Language
    
    Casinos ban if your IP is "London" but your browser time is "New York".
    
    Args:
        page: Patchright page object
        expected_country_code: 'US', 'DE', 'GB', 'BE', etc. (From your Proxy info)
        
    Raises:
        SanityCheckException: If proxy location doesn't match browser configuration
    """
    logger.info(f"🔍 Running Network Consistency Check (Expected: {expected_country_code.upper()})...")
    
    ip_data = None
    fetch_errors = []
    
    # List of providers to try (HTTPS preferred, HTTP fallback)
    # 1. ipapi.co (Rich data: timezone, languages, etc.)
    # 2. ip-api.com (HTTP fallback, less strict on SSL)
    # 3. ipify (Basic IP only, good connectivity check)
    providers = [
        {
            "url": "https://ipapi.co/json/",
            "type": "full", # Expected full json with country/timezone
            "parser": """(data) => { return data; }"""
        },
        {
            "url": "http://ip-api.com/json", 
            "type": "ip_api",
            "parser": """(data) => { 
                return {
                    ip: data.query,
                    country_code: data.countryCode,
                    country: data.country,
                    city: data.city,
                    region: data.region, // We want the CODE (e.g. QC) not Name
                    regionName: data.regionName,
                    timezone: data.timezone
                };
            }"""
        }
    ]

    logger.debug(f"Attempting IP check with {len(providers)} providers...")

    for provider in providers:
        try:
            url = provider["url"]
            logger.debug(f"Trying IP provider: {url}")
            
            # Using fetch for all providers is safer for proxy compatibility in this setup.
            # We add headers to mimic a real user for ipapi.co
            headers = {}
            if "ipapi.co" in url:
                headers = {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
                    "Accept": "application/json",
                    "Referer": "https://www.google.com/"
                }

            # Fetch with timeout and status check
            result = page.evaluate(f"""async (headers) => {{
                try {{
                    const response = await fetch('{url}', {{ 
                        method: 'GET',
                        headers: headers,
                        signal: AbortSignal.timeout(15000) 
                    }});
                    
                    if (!response.ok) {{
                        return {{ error: 'HTTP ' + response.status }};
                    }}
                    
                    const json = await response.json();
                    
                    // Handle case where API returns error inside JSON
                    if (json.error) {{
                         return {{ error: json.error, reason: json.reason }};
                    }}
                    
                    const parser = {provider["parser"]};
                    try {{
                        return parser(json);
                    }} catch (e) {{
                        return {{ error: 'Parser Error: ' + e.toString() }};
                    }}
                }} catch (e) {{
                    return {{ error: e.toString() }};
                }}
            }}""", headers)

            if result.get('error'):
                error_msg = result.get('error')
                reason = result.get('reason', '')
                logger.warning(f"⚠️ Provider {url} failed: {error_msg} {reason}")
                fetch_errors.append(f"{url}: {error_msg} {reason}")
                continue # Try next provider
            
            # If we got here, we have valid data
            ip_data = result
            logger.info(f"✅ IP Check passed using {url}")
            break

        except Exception as e:
            logger.warning(f"⚠️ Provider {url} exception: {e}")
            fetch_errors.append(f"{url}: {e}")
            continue

    # If all providers failed, FAIL HARD (as requested)
    if not ip_data:
        error_summary = "; ".join(fetch_errors)
        logger.error(f"❌ All IP providers failed. Errors: {error_summary}")
        raise SanityCheckException(f"🚨 Network Connection Failed: Unable to verify IP via any provider. Check proxy settings. ({error_summary})")

    logger.debug(f"IP Data: {ip_data}")
        
    # Extract IP info (standardized keys)
    actual_country = ip_data.get('country_code') or ip_data.get('country') or ip_data.get('countryCode')
    ip_address = ip_data.get('ip') or ip_data.get('query') or 'Unknown'
    region = ip_data.get('region') or ip_data.get('regionName') or 'Unknown'
    city = ip_data.get('city') or 'Unknown'
    ip_timezone = ip_data.get('timezone') or 'Unknown'
    ip_languages = ip_data.get('languages', '').split(',')[0] if ip_data.get('languages') else None
    
    # Reset headers
    page.set_extra_http_headers({})
    
    # Get Browser Configuration
    browser_config = page.evaluate("""() => {
        return {
            timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
            language: navigator.language,
            languages: navigator.languages,
            locale: Intl.DateTimeFormat().resolvedOptions().locale
        };
    }""")
        
    browser_tz = browser_config.get('timezone')
    browser_lang = browser_config.get('language')
    
    logger.info(f"🌍 Proxy IP: {ip_address} ({actual_country or 'Unknown'})")
    logger.info(f"🌍 IP Location: {city}, {region}")
    logger.info(f"🕒 IP Timezone: {ip_timezone}")
    logger.info(f"🕒 Browser Timezone: {browser_tz}")
    logger.info(f"🗣️ Browser Language: {browser_lang}")
        
    # Validation: Check for API error response body
    if not actual_country:
        error = ip_data.get('error') or ip_data.get('reason')
        if error:
            logger.warning(f"⚠️ IP API Error: {error}")
            return {"skipped": True}
        else:
            logger.warning("⚠️ IP API: No country code in response")
            return {"skipped": True}
    
    actual_country = actual_country.upper()
    expected_country = expected_country_code.upper()
    
    # Validation 1: Country Code Match
    if actual_country != expected_country:
        raise SanityCheckException(
            f"🚨 COUNTRY MISMATCH: Expected {expected_country}, got {actual_country}"
        )
    
    # Validation 2: Timezone Consistency
    if ip_timezone and ip_timezone != 'Unknown':
        if browser_tz != ip_timezone:
            # Check if they're in the same region
            ip_tz_region = ip_timezone.split('/')[0] if '/' in ip_timezone else ip_timezone
            browser_tz_region = browser_tz.split('/')[0] if '/' in browser_tz else browser_tz
            
            if ip_tz_region != browser_tz_region:
                logger.warning(
                    f"⚠️ TIMEZONE MISMATCH: IP={ip_timezone}, Browser={browser_tz}"
                )
            else:
                logger.info(f"✓ Timezone regions match: {ip_tz_region}")
        else:
            logger.info(f"✓ Timezone exact match: {ip_timezone}")
    
    # Validation 3: Language Consistency
    if ip_languages:
        browser_lang_country = browser_lang.split('-')[-1].upper() if '-' in browser_lang else None
        if browser_lang_country and browser_lang_country != actual_country:
            logger.warning(
                f"⚠️ LANGUAGE MISMATCH: Browser language suggests {browser_lang_country}, "
                f"but IP is in {actual_country}"
            )
        else:
            logger.info(f"✓ Language consistent: {browser_lang}")
    
    logger.success("✅ Network Consistency: Pass")
    
    return {
        "ip": ip_address,
        "country_code": actual_country,
        "region": region,
        "city": city,
        "ip_timezone": ip_timezone,
        "browser_timezone": browser_tz,
        "browser_language": browser_lang,
        "skipped": False
    }
        

def check_dns_leak(page, proxy_country_code):
    """
    Check 3: DNS Leak Detection
    
    Ensures that DNS requests are being resolved by the proxy/VPN and not leaking
    to the local ISP.
    
    Args:
        page: Patchright page object
        proxy_country_code: Expected country code (e.g., 'BE')
        
    Raises:
        SanityCheckException: If DNS location mismatches proxy location
    """
    logger.info("🔍 Running DNS Leak Check...")
    
    # Map common codes to English names for loose matching
    country_map = {
        'BE': 'Belgium',
        'US': 'United States',
        'GB': 'United Kingdom',
        'DE': 'Germany',
        'FR': 'France',
        'NL': 'Netherlands',
        # Add more if needed
    }
    
    try:
        # Navigate to DNS check service
        # edns.ip-api.com returns a simple JSON with DNS resolver info
        page.goto("https://edns.ip-api.com/json", wait_until='domcontentloaded', timeout=10000)
        
        # Parse JSON from body
        dns_data = page.evaluate("() => JSON.parse(document.body.innerText)")
        
        # Extract DNS location
        dns_geo = dns_data.get("dns", {}).get("geo", "Unknown")
        dns_ip = dns_data.get("dns", {}).get("ip", "Unknown")
        
        logger.info(f"📡 DNS Resolver IP: {dns_ip}")
        logger.info(f"📡 DNS Resolver Location: {dns_geo}")
        
        code = proxy_country_code.upper()
        name = country_map.get(code, code) # Fallback to code if name not found
        
        # Looser check: 
        # 1. Exact code match (e.g. "BE")
        # 2. Name in string (e.g. "Belgium" in "Belgium - Cloudflare")
        # 3. Code in string (e.g. "BE" in "BE - Google")
        # 4. Neighbor exception (Common for EU proxies routing via NL)
        is_neighbor = (code == 'BE' and ('Netherlands' in dns_geo or 'NL' in dns_geo))
        
        match = (code == dns_geo) or (name in dns_geo) or (code in dns_geo) or is_neighbor
        
        if not match:
            logger.warning(f"⚠️ WARNING: DNS Country ({dns_geo}) != Proxy Country ({code}). Potential Leak!")
            # We treat this as a FATAL error for high OpSec
            raise SanityCheckException(f"🚨 DNS LEAK DETECTED: Resolver in {dns_geo}, expected {code}")
            
        if is_neighbor:
             logger.warning(f"⚠️ DNS Check: Passthrough via Neighbor ({dns_geo}). Acceptable.")
        else:
             logger.success("✅ DNS Check: Secure (Matches Proxy)")
        return {"leak": False, "dns_geo": dns_geo}
        
    except Exception as e:
        logger.error(f"❌ DNS Check Failed: {e}")
        # If the check itself fails (network error), it's also a risk
        raise SanityCheckException(f"🚨 DNS Check Error: {e}")



def check_ip_quality(page):
    """
    Check 4: IP Quality & Trust Score (The "Real" Protocol)
    
    Verifies that the IP is not flagged as a Datacenter/Hosting range.
    Casinos ban Datacenter IPs instantly. Residential or Mobile is required.
    
    Args:
        page: Patchright page object
        
    Raises:
        SanityCheckException: If IP is detected as Hosting/Datacenter
    """
    logger.info("🔍 Running Deep IP Quality Check...")
    
    # ip-api.com fields: status,message,country,countryCode,timezone,mobile,proxy,hosting,query
    url = "http://ip-api.com/json/?fields=status,message,country,countryCode,timezone,mobile,proxy,hosting,query"
    
    try:
        # We use the robust fetch wrapper pattern (similar to other checks) 
        # to ensure it works through the proxy without "Tunnel" errors.
        result = page.evaluate(f"""async () => {{
            try {{
                const response = await fetch('{url}', {{ signal: AbortSignal.timeout(15000) }});
                if (!response.ok) {{
                    return {{ error: 'HTTP ' + response.status }};
                }}
                return await response.json();
            }} catch (e) {{
                return {{ error: e.toString() }};
            }}
        }}""")
        
        if result.get('error'):
            logger.warning(f"⚠️ IP Quality Check failed to fetch data: {result.get('error')}")
            # We don't fail here because connection might be flaky, but it's a risk.
            # However, since network consistency passed, this might be a specific API issue.
            return {"skipped": True}

        ip_query = result.get("query", "Unknown")
        is_proxy = result.get("proxy", False)
        is_hosting = result.get("hosting", False)
        is_mobile = result.get("mobile", False)
        
        logger.info(f"🛡️ IP Analysis for {ip_query}:")
        logger.info(f"   - Is Mobile? {is_mobile}")
        logger.info(f"   - Is Proxy? {is_proxy}")
        logger.info(f"   - Is Hosting/DataCenter? {is_hosting}")
        
        # CRITICAL FAIL CONDITION: Hosting/Datacenter
        if is_hosting:
            raise SanityCheckException(
                f"🚨 RED FLAG: IP {ip_query} detected as Data Center/Hosting! Casino will ban."
            )
            
        # WARNING CONDITION: Public Proxy flag
        if is_proxy:
            logger.warning("⚠️ Note: IP is flagged as a known proxy/VPN exit node. Moderate Risk.")
        else:
            logger.success("✅ IP Quality: Clean (Not flagged as proxy/hosting)")
            
        return {
            "ip": ip_query,
            "is_hosting": is_hosting,
            "is_proxy": is_proxy,
            "is_mobile": is_mobile
        }
            
    except SanityCheckException:
        raise
    except Exception as e:
        logger.error(f"⚠️ Could not verify proxy quality: {e}")
        return {"error": str(e)}


def check_hardware_fingerprint(page):
    """
    Check 5: The "Hardware Identity" - WebGL & Render
    
    Ensures AdsPower didn't fallback to a software renderer (which screams "VM/Server").
    
    Args:
        page: Patchright page object
        
    Raises:
        SanityCheckException: If hardware profile looks suspicious
    """
    logger.info("🔍 Running Hardware Fingerprint Check...")
    
    try:
        gpu_info = page.evaluate("""() => {
            const canvas = document.createElement('canvas');
            const gl = canvas.getContext('webgl');
            
            if (!gl) {
                return {
                    vendor: 'WEBGL_NOT_SUPPORTED',
                    renderer: 'WEBGL_NOT_SUPPORTED'
                };
            }
            
            const debugInfo = gl.getExtension('WEBGL_debug_renderer_info');
            
            if (!debugInfo) {
                return {
                    vendor: 'DEBUG_INFO_NOT_AVAILABLE',
                    renderer: 'DEBUG_INFO_NOT_AVAILABLE'
                };
            }
            
            return {
                vendor: gl.getParameter(debugInfo.UNMASKED_VENDOR_WEBGL),
                renderer: gl.getParameter(debugInfo.UNMASKED_RENDERER_WEBGL)
            }
        }""")
        
        vendor = gpu_info.get('vendor', '')
        renderer = gpu_info.get('renderer', '')
        
        logger.info(f"🖥️ GPU Vendor: {vendor}")
        logger.info(f"🖥️ GPU Renderer: {renderer}")
        
        # Red Flag: SwiftShader is Google's software renderer
        # If you see this, hardware acceleration is broken/disabled. BOTS use this.
        if "SwiftShader" in renderer:
            raise SanityCheckException(
                "🚨 HARDWARE FAIL: SwiftShader detected. Profile looks like a Headless Server."
            )
        
        # Red Flag: No WebGL support
        if vendor == 'WEBGL_NOT_SUPPORTED':
            raise SanityCheckException(
                "🚨 HARDWARE FAIL: WebGL not supported. This is highly suspicious."
            )
        
        logger.success("✅ Hardware: Valid")
        
        return gpu_info
        
    except Exception as e:
        # Don't fail on hardware check errors, just warn
        logger.warning(f"⚠️ Hardware Fingerprint Check Error: {e}")
        return {"vendor": "ERROR", "renderer": "ERROR"}


def run_all_checks(page, expected_country_code):
    """
    Run all sanity checks in sequence.
    
    Args:
        page: Patchright page object
        expected_country_code: Expected country code for proxy validation
        
    Returns:
        dict: Combined validation report
        
    Raises:
        SanityCheckException: If any critical check fails
    """
    logger.info("🛡️ Starting Full Sanity Check Suite...")
    
    results = {
        "automation_flags": None,
        "network_consistency": None,
        "dns_leak": None,
        "ip_quality": None,
        "hardware_fingerprint": None,
        "passed": False
    }
    
    try:
        # Run checks in order
        results["automation_flags"] = check_automation_flags(page)
        results["network_consistency"] = check_network_consistency(page, expected_country_code)
        
        # IP Quality Check (The "Real" Protocol) - Run early to detect hosting IPs
        results["ip_quality"] = check_ip_quality(page)
        
        # DNS Leak Check
        results["dns_leak"] = check_dns_leak(page, expected_country_code)
        
        results["hardware_fingerprint"] = check_hardware_fingerprint(page)
        
        results["passed"] = True
        logger.success("🛡️ All Sanity Checks Passed!")
        
    except SanityCheckException as e:
        logger.error(f"❌ Sanity Check Failed: {e}")
        results["passed"] = False
        raise
    
    return results
