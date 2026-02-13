import logging
import os
import re
import mailslurp_client
from mailslurp_client.rest import ApiException

logger = logging.getLogger(__name__)
    
class EmailService: # Handle email using MailSlurp API
    def __init__(self):
        self.api_key = os.environ.get("MAILSLURP_API_KEY")
        if not self.api_key:
            raise Exception("MAILSLURP_API_KEY environment variable not set")
            
        configuration = mailslurp_client.Configuration()
        configuration.api_key['x-api-key'] = self.api_key
        self.api_client = mailslurp_client.ApiClient(configuration)
        self.inbox_controller = mailslurp_client.InboxControllerApi(self.api_client)
        self.wait_controller = mailslurp_client.WaitForControllerApi(self.api_client)
        self.email = None
        self.inbox_id = None
        self.session_id = None

    def get_email(self): # Creates a new inbox on MailSlurp
        try:
            inbox = self.inbox_controller.create_inbox()
            self.email = inbox.email_address
            self.inbox_id = inbox.id
            self.session_id = f"{self.inbox_id}" # Store inbox ID for later
            logger.info(f"Generated MailSlurp email: {self.email}")
            return self.email
        except ApiException as e:
            logger.error(f"Failed to create MailSlurp inbox: {e}")
            raise

    def login(self, email, session_id): # Restores session
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
