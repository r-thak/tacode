"""
Selects which EmailService implementation to use. Both expose the same
interface: get_email(), login(email, session_id), wait_for_verification_code(),
and close(). MailSlurp stays the default -- it's the one that's actually a
maintained API; guerrillamail is a browser-driven scrape of a site whose
markup we don't control, opt in explicitly.

    EMAIL_PROVIDER=mailslurp       (default) -- src/email_service_mailslurp.py
    EMAIL_PROVIDER=guerrillamail   -- src/email_service_guerrillamail.py
"""
import os

_provider = os.environ.get("EMAIL_PROVIDER", "mailslurp").strip().lower()

if _provider == "guerrillamail":
    from email_service_guerrillamail import EmailService
elif _provider == "mailslurp":
    from email_service_mailslurp import EmailService
else:
    raise ValueError(f"Unknown EMAIL_PROVIDER '{_provider}'. Use 'mailslurp' or 'guerrillamail'.")

__all__ = ["EmailService"]
