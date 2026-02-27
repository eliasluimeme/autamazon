import imaplib
import email
import re
import time
from loguru import logger

def get_otp_from_imap(mail_address, password, server="outlook.office365.com", timeout=60):
    """
    Retrieves the 6-digit Amazon OTP code via IMAP.
    This is much faster and more reliable than browser automation.
    """
    logger.info(f"📧 Connecting to IMAP for {mail_address}...")
    start_time = time.time()
    
    try:
        # Connect to server
        mail = imaplib.IMAP4_SSL(server)
        mail.login(mail_address, password)
        
        while time.time() - start_time < timeout:
            mail.select("inbox")
            # Search for Amazon's verification email
            # We look for UNSEEN or just the most recent from Amazon
            status, messages = mail.search(None, '(FROM "amazon.com")')
            
            if status == 'OK' and messages[0]:
                msg_ids = messages[0].split()
                # Get the latest message
                latest_msg_id = msg_ids[-1]
                
                status, msg_data = mail.fetch(latest_msg_id, '(RFC822)')
                if status == 'OK':
                    for response_part in msg_data:
                        if isinstance(response_part, tuple):
                            msg = email.message_from_bytes(response_part[1])
                            
                            # Get body
                            body = ""
                            if msg.is_multipart():
                                for part in msg.walk():
                                    if part.get_content_type() == "text/plain":
                                        body = part.get_payload(decode=True).decode()
                                        break
                            else:
                                body = msg.get_payload(decode=True).decode()
                            
                            # Extract 6-digit code
                            match = re.search(r'(\d{6})', body)
                            if match:
                                otp = match.group(1)
                                logger.success(f"✅ Found Amazon OTP via IMAP: {otp}")
                                # Clean up: mark as delete or read? Let's just leave it.
                                mail.logout()
                                return otp
            
            logger.debug("OTP email not found yet, retrying in 5s...")
            time.sleep(5)
            
        mail.logout()
    except Exception as e:
        logger.error(f"IMAP error: {e}")
        
    return None
