import requests
import time
import re
import logging
import uuid

logger = logging.getLogger(__name__)

class EmailService:
    """
    Service to handle temporary email addresses using Mail.tm API.
    More robust than 1secmail for automated testing.
    """
    def __init__(self):
        self.api_url = "https://api.mail.tm"
        self.email = None
        self.token = None
        self.account_id = None
        self.password = str(uuid.uuid4()) # Random password for the temp account

    def get_email(self):
        """Creates a new temporary email account on Mail.tm."""
        try:
            # 1. Get available domains
            domains_res = requests.get(f"{self.api_url}/domains")
            domains_res.raise_for_status()
            domain = domains_res.json()['hydra:member'][0]['domain']
            
            # 2. Create account
            self.email = f"taco_{uuid.uuid4().hex[:10]}@{domain}"
            account_data = {
                "address": self.email,
                "password": self.password
            }
            create_res = requests.post(f"{self.api_url}/accounts", json=account_data)
            create_res.raise_for_status()
            self.account_id = create_res.json()['id']
            
            # 3. Get JWT Token
            token_res = requests.post(f"{self.api_url}/token", json=account_data)
            token_res.raise_for_status()
            self.token = token_res.json()['token']
            
            logger.info(f"Generated Mail.tm email: {self.email}")
            return self.email
            
        except Exception as e:
            logger.error(f"Failed to initialize Mail.tm account: {e}")
            raise

    def check_inbox(self):
        """Checks for new messages in the Mail.tm inbox."""
        if not self.token:
            return []
        
        headers = {"Authorization": f"Bearer {self.token}"}
        try:
            response = requests.get(f"{self.api_url}/messages", headers=headers)
            response.raise_for_status()
            return response.json()['hydra:member']
        except Exception as e:
            logger.error(f"Error checking Mail.tm inbox: {e}")
            return []

    def get_message_content(self, msg_id):
        """Retrieves the full content of a specific message."""
        headers = {"Authorization": f"Bearer {self.token}"}
        try:
            response = requests.get(f"{self.api_url}/messages/{msg_id}", headers=headers)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Error reading message {msg_id}: {e}")
            return {}

    def wait_for_verification_code(self, timeout=300):
        """Polls the inbox for a verification code."""
        logger.info("Polling Mail.tm for verification email...")
        start_time = time.time()
        while time.time() - start_time < timeout:
            messages = self.check_inbox()
            for msg in messages:
                # Mail.tm messages have a 'subject' and 'intro' usually containing the code
                # But we'll fetch the full body to be sure
                content = self.get_message_content(msg['id'])
                body = content.get('text', '') or content.get('html', '')
                
                # Search for a 6-digit code
                match = re.search(r"\b(\d{6})\b", str(body))
                if match:
                    code = match.group(1)
                    logger.info(f"Code found: {code}")
                    return code
                
            time.sleep(10)
        raise Exception("Timed out waiting for verification email.")
