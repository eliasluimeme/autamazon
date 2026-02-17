import random
import time
from loguru import logger
from patchright.sync_api import Page

# Define the Database
SITE_DATABASE = {
    # --- GLOBAL (Mix these in for everyone) ---
    "GLOBAL": [
        "https://www.youtube.com/",
        "https://www.wikipedia.org/",
        "https://www.reddit.com/",
        "https://www.twitch.tv/",
        "https://stackoverflow.com/"
    ],

    # --- 🇦🇺 AUSTRALIA (AU) ---
    "AU": [
        "https://www.news.com.au/",       # Major News
        "https://www.woolworths.com.au/", # Major Grocery/Shopping
        "https://www.realestate.com.au/", # Real Estate (High Trust)
        "https://www.gumtree.com.au/",    # Classifieds
        "https://www.jbhifi.com.au/"      # Electronics
    ],

    # --- 🇮🇹 ITALY (IT) ---
    "IT": [
        "https://www.repubblica.it/",     # Major News
        "https://www.subito.it/",         # Classifieds (Essential IT Cookie)
        "https://www.immobiliare.it/",    # Real Estate
        "https://www.amazon.it/",         # Shopping
        "https://www.gazzetta.it/"        # Sports News
    ],

    # --- 🇨🇦 CANADA (CA) ---
    "CA": [
        "https://www.cbc.ca/",            # National Broadcaster
        "https://www.kijiji.ca/",         # Classifieds (The #1 CA Trust Cookie)
        "https://www.canadiantire.ca/",   # Retail
        "https://www.realtor.ca/",        # Real Estate
        "https://www.theweathernetwork.com/ca" # Utility
    ],

    # --- 🇪🇸 SPAIN (ES) ---
    "ES": [
        "https://www.elmundo.es/",        # Major News
        "https://www.milanuncios.com/",   # Classifieds
        "https://www.idealista.com/",     # Real Estate
        "https://www.elcorteingles.es/",  # Major Retail
        "https://www.marca.com/"          # Sports
    ],

    # --- 🇩🇪 GERMANY (DE) ---
    "DE": [
        "https://www.spiegel.de/",        # Major News
        "https://www.kleinanzeigen.de/",  # Classifieds (Ex-Ebay, Vital)
        "https://www.otto.de/",           # Shopping
        "https://www.immobilienscout24.de/", # Real Estate
        "https://www.t-online.de/"        # Portal
    ],

    # --- 🇳🇱 NETHERLANDS (NL) ---
    "NL": [
        "https://www.nu.nl/",             # Major News
        "https://www.marktplaats.nl/",    # Classifieds (The #1 NL Trust Cookie)
        "https://www.bol.com/nl/",        # Shopping (The "Amazon" of NL)
        "https://www.funda.nl/",          # Real Estate
        "https://www.telegraaf.nl/"       # News
    ],

    # --- 🇷🇴 ROMANIA (RO) ---
    "RO": [
        "https://www.digi24.ro/",         # News
        "https://www.emag.ro/",           # Shopping (The "Amazon" of RO)
        "https://www.olx.ro/",            # Classifieds
        "https://www.imobiliare.ro/",     # Real Estate
        "https://www.adevarul.ro/"        # News
    ],

    # --- 🇵🇱 POLAND (PL) ---
    "PL": [
        "https://www.onet.pl/",           # Major Portal
        "https://allegro.pl/",            # Shopping (Massive PL Trust Signal)
        "https://www.olx.pl/",            # Classifieds
        "https://www.wp.pl/",             # Portal
        "https://www.otodom.pl/"          # Real Estate
    ],

    # --- 🇧🇪 BELGIUM (BE) ---
    "BE": [
        "https://www.hln.be/",            # News (Flemish)
        "https://www.2dehands.be/",       # Classifieds
        "https://www.immoweb.be/",        # Real Estate
        "https://www.bol.com/be/",        # Shopping
        "https://www.lesoir.be/"          # News (French)
    ],

    # --- 🇺🇦 UKRAINE (UA) ---
    "UA": [
        "https://www.pravda.com.ua/",     # News
        "https://rozetka.com.ua/",        # Shopping (The "Amazon" of UA)
        "https://www.olx.ua/",            # Classifieds
        "https://sinoptik.ua/",           # Weather
        "https://korrespondent.net/"      # News
    ]
}

def get_sites_for_country(country_code):
    """
    Returns a mix of Global + Local sites.
    """
    country_code = country_code.upper()
    
    # 1. Start with Global sites (Pick 2 random)
    targets = random.sample(SITE_DATABASE["GLOBAL"], 2)
    
    # 2. Add Local sites (Pick 1 or 2 random)
    local_sites = SITE_DATABASE.get(country_code, [])
    
    if local_sites:
        # Pick up to 2 local sites
        targets.extend(random.sample(local_sites, min(2, len(local_sites))))
    else:
        # Fallback if country not in list: Use more global sites
        logger.warning(f"⚠️ Warning: No specific sites list for {country_code}. Using Global only.")
        targets.extend(random.sample(SITE_DATABASE["GLOBAL"], 1))
        
    random.shuffle(targets)
    return targets

def handle_cookie_popups(page: Page):
    """
    Attempts to click 'Accept' buttons in various languages.
    """
    # Regex to match "Accept", "Agree", "Allow" in:
    # EN, DE, IT, ES, NL, PL, RO, FR, UA/RU
    accept_regex = (
        "text=/^("
        "Accept|Agree|Allow|Consent|Okay|Got it|"  # English
        "Akzeptieren|Zustimmen|Verstanden|Einverstanden|" # German
        "Accetta|Acconsento|Accettare|"             # Italian
        "Aceptar|Consentir|Vale|"                   # Spanish
        "Accepteren|Akkoord|Toestaan|"              # Dutch
        "Zaakceptuj|Zgoda|Przejdź|"                 # Polish
        "Acceptă|De acord|"                         # Romanian
        "Accepter|J'accepte|Oui|"                   # French
        "Прийняти|Згоден|Погодитись"                # Ukrainian
        ")$/i"
    )
    
    try:
        # Wait briefly for popup
        time.sleep(2)
        
        # Try to click the button
        # We use .first to just click the first positive match found
        button = page.locator(accept_regex).first
        if button.is_visible():
            logger.info("   🍪 Clicking Cookie Consent Button...")
            button.click()
            time.sleep(1.5) # Wait for banner to disappear
    except Exception:
        # It's okay if we miss some, we just move on
        pass

def human_scroll(page: Page):
    """
    Smooth random scroll to look human and trigger lazy-loaded cookies.
    """
    try:
        # Scroll down
        page.evaluate("window.scrollTo({top: 500, behavior: 'smooth'});")
        time.sleep(1)
        page.evaluate("window.scrollTo({top: 1000, behavior: 'smooth'});")
        time.sleep(1)
        # Scroll back up a bit
        page.evaluate("window.scrollTo({top: 200, behavior: 'smooth'});")
    except Exception:
        pass

def generate_natural_history(page: Page, country_code="US"):
    """
    Visits sites relevant to the Proxy location to generate UNIQUE cookies and history.
    """
    target_sites = get_sites_for_country(country_code)
    logger.info(f"🍪 Cookie Farming for {country_code}: Visiting {len(target_sites)} sites...")
    
    for url in target_sites:
        try:
            logger.info(f"   ➡️ Visiting: {url}")
            page.goto(url, timeout=45000, wait_until="domcontentloaded")
            
            # --- BEHAVIORAL LOGIC ---
            # 1. Accept Cookies (If a popup appears)
            handle_cookie_popups(page)

            # 2. Scroll to trigger lazy loading pixels
            human_scroll(page)
            
            # 3. Stay on page
            time.sleep(random.uniform(3, 7))
            
        except Exception as e:
            logger.warning(f"   ⚠️ Skipped {url}: {e}")
            
    logger.success("✅ Cookie Generation Complete. Profile is 'Warm'.")
