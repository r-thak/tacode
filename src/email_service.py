import logging
import os
import re
import random

import mailslurp_client
from mailslurp_client.rest import ApiException

logger = logging.getLogger(__name__)
    
class EmailService:
    def __init__(self):
        self.api_key = os.environ.get("MAILSLURP_API_KEY")
        if not self.api_key:
            raise Exception("MAILSLURP_API_KEY environment variable not set")
            
        configuration = mailslurp_client.Configuration()
        configuration.host = "https://api.mailslurp.com"
        configuration.api_key['x-api-key'] = self.api_key
        self.api_client = mailslurp_client.ApiClient(configuration)
        self.inbox_controller = mailslurp_client.InboxControllerApi(self.api_client)
        self.wait_controller = mailslurp_client.WaitForControllerApi(self.api_client)
        self.email = None
        self.inbox_id = None
        self.session_id = None
        self.blocked_domains_file = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "blocked_domains.txt")

    def _get_blocked_domains(self):
        if not os.path.exists(self.blocked_domains_file):
            return []
        try:
            with open(self.blocked_domains_file, 'r') as f:
                return [line.strip().lower() for line in f if line.strip()]
        except Exception as e:
            logger.error(f"Error reading blocked domains: {e}")
            return []

    def get_email(self):
        blocked_domains = self._get_blocked_domains()
        max_attempts = 5
        
        for attempt in range(max_attempts):
            try:
                taco_id = random.randint(1000, 9999)
                inbox = self.inbox_controller.create_inbox(
                    prefix=f"taco{taco_id}",
                    use_domain_pool=True
                )
                
                self.email = inbox.email_address
                domain = self.email.split('@')[1]
                
                # Check if this domain is blocked
                if domain.lower() in blocked_domains:
                    logger.warning(f"Generated email domain {domain} is blocked. Retrying (Attempt {attempt + 1}/{max_attempts})...")
                    continue

                self.inbox_id = inbox.id
                self.session_id = f"{self.inbox_id}" # Store inbox ID for later
                
                logger.info(f"Generated MailSlurp email: {self.email}")
                return self.email
                
            except ApiException as e:
                logger.error(f"Failed to create MailSlurp inbox: {e}")
                if attempt == max_attempts - 1:
                    raise
        
        raise Exception(f"Failed to generate a non-blocked email after {max_attempts} attempts.")

    def login(self, email, session_id):
        self.email = email
        self.inbox_id = session_id 
        self.session_id = session_id
        return True

    def wait_for_verification_code(self, timeout=300000):
        logger.info(f"Polling MailSlurp ({self.email}) for verification email...")
        try:
            email = self.wait_controller.wait_for_latest_email(
                inbox_id=self.inbox_id,
                timeout=int(timeout),
                unread_only=True
            )
            
            body = email.body or ""
            subject = email.subject or ""
            logger.debug(f"Email received. Subject: {subject}")
            
            def find_code(text):
                matches = re.finditer(r"\b(\d{6})\b", str(text))
                candidates = []
                for match in matches:
                    val = match.group(1)
                    if val != "000000":
                        candidates.append(val)
                return candidates

            codes = find_code(body)
            if not codes:
                codes = find_code(subject)
            
            if codes:
                code = codes[0]
                logger.info(f"Code found: {code}")
                return code
            else:
                logger.warning(f"Email received but no valid code found.\nSubject: {subject}\nBody Preview: {body[:200]}")
                with open("debug_email_body.txt", "w") as f:
                    f.write(body)
                raise Exception("Email received but code not found (ignored 000000).")
                
        except ApiException as e:
            logger.error(f"MailSlurp wait failed: {e}")
            raise Exception(f"Timed out waiting for verification email: {e}")