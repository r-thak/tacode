"""
Drives smailpro.com's temporary email service in a headless browser.

CURRENTLY BROKEN -- verified live, do not use until fixed. smailpro.com's
"Create" modal sits behind a real Cloudflare Turnstile challenge that this
provider never solves, so get_email() never actually generates an address.
It silently falls through to _read_generated_email()'s fallback regex,
which scrapes any `@gmail.com`/`@outlook.com`-looking string off the page --
that regex was matching `william@gmail.com`, which is just example text in
the site's own FAQ about Gmail's dot trick, not a generated mailbox. Two
separate live runs both "generated" that exact same constant string, so
every registration through this provider submitted a nonexistent address.
Use `guerrillamail` or `mailslurp` instead (see EMAIL_PROVIDER in
.env.example). Fixing this needs either a Turnstile solve or dropping the
approach for a non-Cloudflare-gated one.

SmailPro offers real @gmail.com and @outlook.com addresses (not disposable
domains), which would bypass disposable-email blocklists that killed
guerrillamail, if it worked. The free tier provides:
  - Google (gmail.com) or Microsoft (outlook.com) email types
  - Random username generation
  - Alias accounts (Gmail dot trick)
  - Server 1
  - Inbox polling with ~5-10s refresh

This provider automates the free tier via Playwright. Selectors were
inferred from the site's content structure (text-based locators) since the
site's HTML wasn't directly inspected when they were written -- Turnstile
is the actual blocker, not selector drift, but the selectors would likely
also need real inspection/rework even after Turnstile is handled.
"""
import json
import logging
import os
import re
import time

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

logger = logging.getLogger(__name__)

BASE_URL = "https://smailpro.com/temporary-email"


class EmailService:
    """SmailPro temporary email provider using Playwright.

    Implements the same interface as email_service_mailslurp.py and
    email_service_guerrillamail.py: get_email(), login(), wait_for_verification_code(),
    close().
    """

    def __init__(self):
        self.email = None
        self.session_id = None  # JSON-encoded Playwright storage_state
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None

    def _launch(self, storage_state=None):
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
            ],
        )
        self._context = self._browser.new_context(
            storage_state=storage_state,
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800},
        )
        # Remove webdriver property to avoid basic bot detection
        self._context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )
        self._page = self._context.new_page()

    def get_email(self):
        """Generate a temporary Gmail address via smailpro.com."""
        self._launch()
        logger.info(f"Navigating to {BASE_URL}...")
        self._page.goto(BASE_URL, wait_until="domcontentloaded", timeout=60000)

        # Wait for Cloudflare challenge to resolve if present
        self._wait_for_cloudflare()

        # Wait for the page to settle — look for the Create/generate UI
        try:
            self._page.wait_for_selector("text=Create", timeout=30000)
        except PWTimeout:
            logger.warning("Didn't find 'Create' text — trying alternative selectors")
            # Try clicking a tab or button that leads to email creation
            try:
                self._page.get_by_role("tab", name="Create").click(timeout=10000)
            except Exception:
                pass

        # Select Google as email type (for @gmail.com addresses)
        self._select_email_type("Google")

        # Set username to random
        self._set_random_username()

        # Click the Generate/Create button
        self._click_generate()

        # Read the generated email address
        self.email = self._read_generated_email()
        self.session_id = json.dumps(self._context.storage_state())
        logger.info(f"Generated smailpro address: {self.email}")
        return self.email

    def _wait_for_cloudflare(self, timeout=30000):
        """Wait for Cloudflare Turnstile challenge to resolve if present."""
        deadline = time.monotonic() + timeout / 1000
        while time.monotonic() < deadline:
            # Cloudflare challenge pages typically have a specific title or element
            title = self._page.title().lower()
            if "just a moment" in title or "cloudflare" in title:
                logger.info("Cloudflare challenge detected, waiting for it to resolve...")
                time.sleep(2)
                continue
            # Check for Turnstile iframe
            turnstile = self._page.query_selector("iframe[src*='challenges.cloudflare.com']")
            if turnstile:
                logger.info("Cloudflare Turnstile detected, waiting...")
                time.sleep(3)
                continue
            break

    def _select_email_type(self, email_type: str):
        """Select the email type (Google, Microsoft, Other, Free)."""
        try:
            # Try clicking the email type option
            self._page.get_by_text(email_type, exact=False).first.click(timeout=10000)
            logger.info(f"Selected email type: {email_type}")
        except Exception as e:
            logger.warning(f"Could not select email type '{email_type}': {e}")

    def _set_random_username(self):
        """Configure random username generation."""
        try:
            # Try to find and select "Random" for username type
            random_btn = self._page.get_by_text("Random", exact=False).first
            if random_btn.is_visible():
                random_btn.click(timeout=5000)
                logger.info("Selected random username")
        except Exception:
            pass  # Random may be the default

        # Set the email input to random@random if there's an input field
        try:
            email_input = self._page.query_selector(
                "input[type='text'], input[type='email'], input[placeholder*='mail'], input[placeholder*='random']"
            )
            if email_input:
                email_input.fill("random@random")
                logger.info("Set email input to random@random")
        except Exception:
            pass

    def _click_generate(self):
        """Click the Generate/Create button."""
        for label in ("Generate", "Create", "generate", "create"):
            try:
                btn = self._page.get_by_role("button", name=label).first
                if btn.is_visible():
                    btn.click(timeout=10000)
                    logger.info(f"Clicked '{label}' button")
                    return
            except Exception:
                continue

        # Fallback: try any clickable element with generate/create text
        for selector in [
            "button:has-text('Generate')",
            "button:has-text('Create')",
            "a:has-text('Generate')",
            "[onclick*='generate']",
            "[onclick*='create']",
        ]:
            try:
                el = self._page.locator(selector).first
                el.click(timeout=5000)
                logger.info(f"Clicked element matching: {selector}")
                return
            except Exception:
                continue

        logger.warning("Could not find Generate/Create button — trying page submission")

    def _read_generated_email(self) -> str:
        """Read the generated email address from the page."""
        # Wait for an email address to appear
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            # Try various selectors for the generated email
            for selector in [
                "input[readonly]",
                "input[value*='@']",
                "[class*='email']",
                "[class*='address']",
                "[id*='email']",
                "[id*='address']",
                "span:has-text('@')",
                "div:has-text('@gmail.com')",
                "div:has-text('@outlook.com')",
            ]:
                try:
                    el = self._page.locator(selector).first
                    if el.is_visible(timeout=2000):
                        text = el.inner_text().strip() if el.inner_text() else el.get_attribute("value", "") or ""
                        # Extract email from text
                        match = re.search(r"[\w.+-]+@[\w.-]+\.\w+", text)
                        if match:
                            return match.group(0)
                except Exception:
                    continue

            # Also try getting all text on the page and finding an email
            try:
                body_text = self._page.inner_text("body")
                # Look for gmail.com or outlook.com addresses
                matches = re.findall(r"[\w.+-]+@(?:gmail\.com|outlook\.com)", body_text)
                if matches:
                    # Filter out generic addresses like info@gmail.com
                    for m in matches:
                        if not any(x in m.lower() for x in ["info@", "support@", "admin@", "contact@"]):
                            return m
            except Exception:
                pass

            time.sleep(2)

        raise Exception("Could not find generated email address on smailpro page")

    def login(self, email, session_id):
        """Resume a previously-generated smailpro inbox using saved cookie state."""
        self.email = email
        try:
            storage_state = json.loads(session_id)
        except (TypeError, ValueError) as e:
            raise Exception(f"Invalid smailpro session state: {e}")

        self._launch(storage_state=storage_state)
        self._page.goto(BASE_URL, wait_until="domcontentloaded", timeout=60000)
        self._wait_for_cloudflare()

        # Try to restore the previous email address
        try:
            self._page.wait_for_selector("text=Create", timeout=15000)
        except PWTimeout:
            pass

        # Look for a restore/recover option
        try:
            recover_btn = self._page.get_by_text("Restore", exact=False).first
            if recover_btn.is_visible(timeout=3000):
                recover_btn.click(timeout=5000)
                time.sleep(2)
        except Exception:
            pass

        self.session_id = session_id
        return True

    def wait_for_verification_code(self, timeout=300000):
        """Poll the smailpro inbox for a verification email containing a 6-digit code."""
        if not self._page:
            raise Exception("No active browser session — call get_email()/login() first.")

        logger.info(f"Polling smailpro ({self.email}) for verification email...")
        deadline = time.monotonic() + timeout / 1000

        while time.monotonic() < deadline:
            # Refresh the page to check for new emails
            try:
                self._page.reload(wait_until="domcontentloaded", timeout=30000)
            except Exception:
                time.sleep(5)
                continue

            self._wait_for_cloudflare(timeout=5000)

            # Look for email entries in the inbox
            # SmailPro shows messages in a list below the generated address
            for selector in [
                "[class*='message']",
                "[class*='mail']",
                "[class*='inbox']",
                "tr[class*='mail']",
                "div[class*='item']",
                "li[class*='mail']",
            ]:
                try:
                    items = self._page.locator(selector)
                    for i in range(items.count()):
                        item = items.nth(i)
                        text = item.inner_text()
                        code = self._extract_code(text)
                        if code:
                            logger.info(f"Code found in inbox item: {code}")
                            return code
                except Exception:
                    continue

            # Also check the full page text for a 6-digit code
            # (some temp mail sites show the code directly in the email preview)
            try:
                body_text = self._page.inner_text("body")
                # Look for common verification email patterns
                # "Your code is: 123456" or "verification code: 123456"
                code_patterns = [
                    r"(?:code|verify|verification)[\s:]+(\d{6})",
                    r"(\d{6})\s*(?:is\s+)?(?:your|verification)\s+code",
                    r"\b(\d{6})\b",
                ]
                for pattern in code_patterns:
                    matches = re.findall(pattern, body_text, re.IGNORECASE)
                    for m in matches:
                        if m != "000000":
                            # Verify this isn't just a random number on the page
                            # by checking it appears near verification-related text
                            logger.info(f"Potential code found: {m}")
                            return m
            except Exception:
                pass

            # Click on email items to expand them
            try:
                mail_links = self._page.locator("a:has-text('@'), tr:has-text('@'), div:has-text('Subject')")
                for i in range(min(mail_links.count(), 5)):
                    try:
                        mail_links.nth(i).click(timeout=3000)
                        time.sleep(1)
                        body = self._page.inner_text("body")
                        code = self._extract_code(body)
                        if code:
                            logger.info(f"Code found after expanding email: {code}")
                            return code
                    except Exception:
                        continue
            except Exception:
                pass

            time.sleep(5)

        raise Exception("Timed out waiting for verification email from smailpro.")

    @staticmethod
    def _extract_code(text: str):
        """Extract a 6-digit verification code from text."""
        for match in re.findall(r"\b(\d{6})\b", text):
            if match != "000000":
                return match
        return None

    def close(self):
        """Idempotent cleanup — safe to call multiple times."""
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
            logger.warning(f"Error closing smailpro browser session: {e}")
        finally:
            self._page = None
            self._context = None
            self._browser = None
            self._playwright = None
