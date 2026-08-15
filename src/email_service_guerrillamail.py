"""
Drives guerrillamail.com's actual web UI in a headless browser instead of
calling a temp-mail API. No signup/login needed -- the site hands you a
fresh address as soon as the page loads.

Selectors below were captured against the live site and smoke-tested end to
end while writing this (address generation, inbox row parsing, opening a
message, and session-resume via storage_state all verified working). Like
any scrape of a site you don't control, they can drift if guerrillamail
changes its markup -- there's no API contract backing this.

Known limitations, please read before relying on this:
  - guerrillamail.com's domains (sharklasers.com, guerrillamail.*, grr.la,
    pokemail.net, spam4.me, ...) are some of the most widely blocklisted
    disposable-mail domains that exist. If the mail-domain blocklist was
    what actually killed the archived branch (per the old README), this
    will likely still get blocked -- this replaces the *transport*
    (API -> browser), not the underlying "this is an obviously disposable
    address" problem.
  - Addresses (and their mail) are deleted after ~1 hour, so
    get_code_for_existing_account()/login() only work within that window.
  - There's a reCAPTCHA config referenced on the page (used for things like
    repeated "Forget Me" actions), but it did NOT appear on the plain
    address-generation / inbox-read path tested here. If that changes,
    this stops working -- do not add CAPTCHA-solving to this file.
"""
import json
import logging
import os
import re
import time

from playwright.sync_api import sync_playwright

logger = logging.getLogger(__name__)

BASE_URL = "https://www.guerrillamail.com/"
BLOCKED_DOMAINS_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "blocked_domains.txt")

SEL = {
    "address": "#email-widget",
    "domain_select": "#gm-host-select",
    "mail_rows": "#email_list tr.mail_row",
    "message_body": "#display_email",
}


def _get_blocked_domains():
    if not os.path.exists(BLOCKED_DOMAINS_FILE):
        return []
    try:
        with open(BLOCKED_DOMAINS_FILE, 'r') as f:
            return [line.strip().lower() for line in f if line.strip()]
    except Exception as e:
        logger.error(f"Error reading blocked domains: {e}")
        return []


class EmailService:
    def __init__(self):
        self.email = None
        self.session_id = None  # JSON-encoded Playwright storage_state (carries the PHPSESSID cookie)
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None

    def _launch(self, storage_state=None):
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(headless=True)
        self._context = self._browser.new_context(storage_state=storage_state)
        self._page = self._context.new_page()

    def get_email(self):
        self._launch()
        self._page.goto(BASE_URL, wait_until="domcontentloaded", timeout=30000)
        self._page.wait_for_function(
            "sel => document.querySelector(sel)?.textContent.trim().includes('@')",
            arg=SEL["address"],
            timeout=15000,
        )

        blocked = _get_blocked_domains()
        domain_options = self._page.locator(f"{SEL['domain_select']} option").all_inner_texts()
        tried = set()

        def current_address():
            return self._page.locator(SEL["address"]).inner_text().strip()

        self.email = current_address()
        domain = self.email.split('@')[-1].lower()

        if domain in blocked:
            logger.warning(f"Initial guerrillamail domain {domain} is blocked, trying alternatives...")
            tried.add(domain)
            for option in domain_options:
                if option.lower() in tried or option.lower() in blocked:
                    continue
                self._page.locator(SEL["domain_select"]).select_option(option)
                self._page.wait_for_timeout(1500)
                self.email = current_address()
                domain = self.email.split('@')[-1].lower()
                tried.add(domain)
                if domain not in blocked:
                    break
            else:
                self.session_id = json.dumps(self._context.storage_state())
                raise Exception("All guerrillamail domains are blocklisted (see blocked_domains.txt).")

        self.session_id = json.dumps(self._context.storage_state())
        logger.info(f"Generated guerrillamail address: {self.email}")
        return self.email

    def login(self, email, session_id):
        """Reopen a previously-generated inbox using its saved cookie state.
        Only works while the address is still alive (~1hr from creation)."""
        self.email = email
        try:
            storage_state = json.loads(session_id)
        except (TypeError, ValueError) as e:
            raise Exception(f"Invalid guerrillamail session state: {e}")

        self._launch(storage_state=storage_state)
        self._page.goto(BASE_URL, wait_until="domcontentloaded", timeout=30000)
        try:
            self._page.wait_for_function(
                "sel => document.querySelector(sel)?.textContent.trim().includes('@')",
                arg=SEL["address"],
                timeout=15000,
            )
        except Exception as e:
            raise Exception(f"Could not resume guerrillamail inbox for {email} (likely expired): {e}")

        resumed = self._page.locator(SEL["address"]).inner_text().strip()
        if resumed != email:
            logger.warning(f"Resumed inbox address ({resumed}) doesn't match requested ({email}); session may have expired and rolled to a new address.")

        self.session_id = session_id
        return True

    def wait_for_verification_code(self, timeout=300000):
        if not self._page:
            raise Exception("No active browser session -- call get_email()/login() first.")

        logger.info(f"Polling guerrillamail ({self.email}) for verification email...")
        deadline = time.monotonic() + timeout / 1000
        checked_ids = set()

        while time.monotonic() < deadline:
            self._page.goto(BASE_URL, wait_until="domcontentloaded", timeout=30000)
            try:
                self._page.wait_for_selector(SEL["mail_rows"], timeout=5000)
            except Exception:
                time.sleep(3)
                continue

            rows = self._page.locator(SEL["mail_rows"])
            for i in range(rows.count()):
                row = rows.nth(i)
                row_id = row.get_attribute("id")
                if not row_id or row_id in checked_ids:
                    continue

                link = row.locator("a").first
                link.click()
                try:
                    self._page.wait_for_function(
                        "sel => document.querySelector(sel)?.innerText.trim().length > 0",
                        arg=SEL["message_body"],
                        timeout=10000,
                    )
                except Exception:
                    checked_ids.add(row_id)
                    continue

                body = self._page.locator(SEL["message_body"]).inner_text()
                code = self._extract_code(body)
                if code:
                    logger.info(f"Code found: {code}")
                    return code

                checked_ids.add(row_id)

            time.sleep(3)

        raise Exception("Timed out waiting for verification email.")

    @staticmethod
    def _extract_code(text: str):
        for match in re.findall(r"\b(\d{6})\b", text):
            if match != "000000":
                return match
        return None

    def close(self):
        """Idempotent -- safe to call more than once (callers' finally blocks
        may double-close after an earlier explicit close)."""
        if not any([self._context, self._browser, self._playwright]):
            return
        try:
            if self._context:
                self._context.close()
            if self._browser:
                self._browser.close()
            if self._playwright:
                self._playwright.stop()
        except Exception as e:
            logger.warning(f"Error closing guerrillamail browser session: {e}")
        finally:
            self._page = None
            self._context = None
            self._browser = None
            self._playwright = None
