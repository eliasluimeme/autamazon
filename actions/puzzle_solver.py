"""
Amazon Puzzle Solver (Funcaptcha / Arkose)

Handles the "Solve this puzzle to protect your account" challenge.
This is typically a visual puzzle (pick the image with X).
Currently implements a manual intervention strategy.
"""

import time
from loguru import logger

def handle_puzzle_step(page) -> bool:
    """
    Handle the Amazon puzzle/challenge step.
    
    Prompts the user to solve the puzzle manually and waits for completion.
    """
    logger.warning("🧩 Amazon Puzzle Detected - MANUAL INTERVENTION REQUIRED 🧩")
    logger.warning("👉 Please switch to the browser and solve the puzzle manually.")
    
    try:
        # Prompt user in terminal
        print("\n" + "="*60)
        print("   >>>  PLEASE SOLVE PUZZLE MANUALLY  <<<   ")
        print("   (Will auto-detect when solved and proceed)")
        print("="*60 + "\n")
        
        # Poll for completion
        max_wait_time = 300  # 5 minutes
        poll_interval = 2
        elapsed = 0
        
        while elapsed < max_wait_time:
            time.sleep(poll_interval)
            elapsed += poll_interval
            
            # Check if we moved past the puzzle
            try:
                # 1. Check URL for next steps (verification, otp, etc.)
                url = page.url.lower()
                if any(x in url for x in ["verification", "otp", "signin", "ap/cvf/approval"]):
                    # If we are verifying, we passed the puzzle
                    logger.info(f"✅ Puzzle appears solved! URL changed to: {url[:50]}...")
                    time.sleep(1)
                    return True
                
                # 2. Check content for next step indicators
                try:
                    if (page.locator("text='Verify email address'").first.is_visible() or
                        page.locator("text='Enter the code'").first.is_visible() or
                        page.locator("input[name='code']").first.is_visible()):
                        logger.info("✅ Puzzle solved! Verification step detected.")
                        return True
                except:
                    pass
                
                # 3. Check if puzzle content is GONE
                # The puzzle usually has text "Solve this puzzle" or specific iframe
                try:
                    is_visible = page.locator("text='Solve this puzzle'").first.is_visible()
                    current_url = page.url.lower()

                    # Add detailed debug info
                    if elapsed % 10 == 0:
                        logger.debug(f"Puzzle check: Visible={is_visible}, URL={current_url}, 'arb=' in URL={'arb=' in current_url}")
                    
                    if not is_visible:
                        # Double check to be sure it didn't just flicker
                        time.sleep(2)
                        
                        # Check URL again: if "arb=" is gone, that's a good sign
                        current_url_check = page.url.lower()
                        if "arb=" not in current_url_check and not page.locator("text='Solve this puzzle'").first.is_visible():
                            logger.info("✅ Puzzle text gone and URL clean (assumed solved)")
                            return True
                except:
                    pass
                    
            except Exception as e:
                logger.debug(f"Puzzle poll check error: {e}")
            
            if elapsed % 30 == 0:
                logger.info(f"⏳ Still waiting for Puzzle solution... ({elapsed}s elapsed)")
                
        logger.error("Puzzle timeout - user did not solve within 5 minutes")
        return False

    except Exception as e:
        logger.error(f"Puzzle handling failed: {e}")
        return False
