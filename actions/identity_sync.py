
import re
from loguru import logger
from amazon.identity_manager import find_identity_by_email, get_identity_manager, Identity

def resolve_identity_from_session(page, current_identity=None):
    """
    Attempts to identify the currently logged-in user from the browser session
    and returns the matching Identity object.
    
    Args:
        page: Playwright page object
        current_identity: The identity we think we are using (optional)
        
    Returns:
        Identity object (updated) or current_identity if resolution fails
    """
    logger.info("🕵️ Resolving identity from browser session...")
    
    try:
        # 1. Check "Hello, Name" in nav bar
        # Selector: #nav-link-accountList-nav-line-1
        try:
            nav_line = page.locator("#nav-link-accountList-nav-line-1").first
            if nav_line.is_visible(timeout=3000):
                text = nav_line.inner_text().strip()
                # Format: "Hello, Dominique" or "Hello, sign in"
                if "sign in" in text.lower():
                    logger.info("Not logged in (Nav bar says 'sign in')")
                    return current_identity
                
                # Extract name
                match = re.search(r"Hello, (.+)", text)
                if match:
                    name_on_screen = match.group(1).strip()
                    logger.info(f"✓ Detected user name on screen: {name_on_screen}")
                    
                    # If we already have an identity and the name matches, we are good
                    if current_identity and name_on_screen.lower() in current_identity.firstname.lower():
                        logger.info(f"✓ Current identity '{current_identity.firstname}' matches screen name")
                        return current_identity
                    
                    # Otherwise, lookup by firstname in used identities
                    # This is loose matching, but better than nothing
                    found = _find_identity_by_firstname(name_on_screen)
                    if found:
                        logger.success(f"✓ Matched session to used identity: {found.email}")
                        return found
                    else:
                        logger.warning(f"Could not find identity matching name '{name_on_screen}' in records")
        except Exception as e:
            logger.debug(f"Nav bar detection failed: {e}")
            
    except Exception as e:
        logger.error(f"Identity resolution failed: {e}")
        
    return current_identity

def _find_identity_by_firstname(firstname: str):
    """
    Helper to search identities by first name.
    """
    manager = get_identity_manager()
    target_name = firstname.lower()
    
    # Check used files first
    for filepath in [manager.used_file, manager.source_file]:
        try:
            with open(filepath, 'r') as f:
                for line in f:
                    identity = Identity.from_line(line)
                    if identity and identity.firstname.lower() == target_name:
                        return identity
        except:
            pass
    return None
