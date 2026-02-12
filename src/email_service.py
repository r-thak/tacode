
import requests
import time
import re

class EmailService:
    """
    Service to handle temporary email addresses and verification codes.
    Defaults to 1secmail.com due to its simple, keyless public API.
    """
    def __init__(self):
        self.api_url = "https://www.1secmail.com/api/v1/"
        self.email = None
        self.login = None
        self.domain = None

    def get_email(self):
        """Generates a new temporary email address."""
        # 1secmail has specific domains we can use
        reg_domains = requests.get(f"{self.api_url}?action=getDomainList").json()
        
        # Filter out domains that are commonly blocked (like 1secmail.com/net/org)
        # We found that domains like vjuum.com or laafd.com bypass the Taco Bell hang.
        filtered_domains = [d for d in reg_domains if "1secmail" not in d]
        
        if filtered_domains:
            # Prefer the non-obvious domains
            self.domain = filtered_domains[0]
        else:
            self.domain = reg_domains[0]

        # Generate a random login name (e.g., taco12345)
        self.login = f"taco{int(time.time())}"
        self.email = f"{self.login}@{self.domain}"
        print(f"Generated email: {self.email}")
        return self.email

    def check_inbox(self):
        """Checks for new messages in the inbox."""
        if not self.login:
            return []
        
        url = f"{self.api_url}?action=getMessages&login={self.login}&domain={self.domain}"
        response = requests.get(url)
        return response.json()

    def get_message_content(self, msg_id):
        """Retrieves the full content of a specific message."""
        url = f"{self.api_url}?action=readMessage&login={self.login}&domain={self.domain}&id={msg_id}"
        return requests.get(url).json()

    def wait_for_verification_code(self, timeout=300):
        """Polls the inbox for a verification code."""
        print("Polling for verification email...")
        start_time = time.time()
        while time.time() - start_time < timeout:
            messages = self.check_inbox()
            for msg in messages:
                content = self.get_message_content(msg['id'])
                body = content.get('textBody', '') or content.get('body', '')
                
                # Search for a 6-digit code
                match = re.search(r"\b(\d{6})\b", body)
                if match:
                    code = match.group(1)
                    print(f"Code found: {code}")
                    return code
                
            time.sleep(10)
        raise Exception("Timed out waiting for verification email.")

# Optional: Add a class for TempMail.org if the user provides an API key
class TempMailOrgService:
    def __init__(self, api_key):
        self.api_key = api_key
        self.base_url = "https://privatix-temp-mail-v1.p.rapidapi.com/request/"
        self.headers = {
            "X-RapidAPI-Key": self.api_key,
            "X-RapidAPI-Host": "privatix-temp-mail-v1.p.rapidapi.com"
        }

    # ... implementation for temp-mail.org API ...
