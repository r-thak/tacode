import os
import logging
import asyncio
import random
import time

from appium.webdriver.common.appiumby import AppiumBy
from selenium.common.exceptions import NoSuchElementException

from email_service import EmailService
from database import Database

logger = logging.getLogger(__name__)

# --- Element locators -------------------------------------------------------
# These are best-guess placeholders (Android/Compose naming conventions for a
# retail ordering app) and have NOT been verified against the real Taco Bell
# app, since that requires an APK + a booted emulator to inspect with Appium
# Inspector (`appium inspector`, or `adb shell uiautomator dump`). Each list
# is tried in order; update these once you've captured the real element
# ids/labels for your APK version.
SELECTORS = {
    "sign_up_entry": [
        (AppiumBy.ACCESSIBILITY_ID, "Sign Up"),
        (AppiumBy.XPATH, "//*[@text='Sign Up' or @text='Create Account' or @content-desc='Sign Up']"),
    ],
    "email_input": [
        (AppiumBy.ID, "com.tacobell.ordering:id/email_input"),
        (AppiumBy.ACCESSIBILITY_ID, "Email Address"),
        (AppiumBy.XPATH, "//android.widget.EditText[contains(@resource-id, 'email')]"),
    ],
    "confirm_email_button": [
        (AppiumBy.ID, "com.tacobell.ordering:id/confirm_button"),
        (AppiumBy.XPATH, "//*[@text='CONFIRM' or @text='Confirm' or @text='Continue']"),
    ],
    "code_input": [
        (AppiumBy.ID, "com.tacobell.ordering:id/verification_code_input"),
        (AppiumBy.ACCESSIBILITY_ID, "Enter Code"),
        (AppiumBy.XPATH, "//android.widget.EditText[contains(@resource-id, 'code')]"),
    ],
    "confirm_code_button": [
        (AppiumBy.ID, "com.tacobell.ordering:id/confirm_button"),
        (AppiumBy.XPATH, "//*[@text='Confirm' or @text='Verify']"),
    ],
    "first_name_input": [
        (AppiumBy.ID, "com.tacobell.ordering:id/first_name_input"),
        (AppiumBy.XPATH, "//android.widget.EditText[contains(@resource-id, 'first_name') or contains(@resource-id, 'firstName')]"),
    ],
    "last_name_input": [
        (AppiumBy.ID, "com.tacobell.ordering:id/last_name_input"),
        (AppiumBy.XPATH, "//android.widget.EditText[contains(@resource-id, 'last_name') or contains(@resource-id, 'lastName')]"),
    ],
    "password_input": [
        (AppiumBy.ID, "com.tacobell.ordering:id/password_input"),
        (AppiumBy.XPATH, "//android.widget.EditText[contains(@resource-id, 'password')]"),
    ],
    "zip_input": [
        (AppiumBy.ID, "com.tacobell.ordering:id/zip_input"),
        (AppiumBy.XPATH, "//android.widget.EditText[contains(@resource-id, 'zip')]"),
    ],
    "terms_checkbox": [
        (AppiumBy.XPATH, "(//android.widget.CheckBox)[last()]"),
    ],
    "create_account_button": [
        (AppiumBy.ID, "com.tacobell.ordering:id/submit_button"),
        (AppiumBy.XPATH, "//*[@text='Create Account' or @text='Sign Up' or @text='Finish']"),
    ],
    "cookie_agree_button": [
        (AppiumBy.XPATH, "//*[@text='AGREE' or @text='Accept' or @text='Allow']"),
    ],
}


class ElementNotFound(Exception):
    pass


class TacoBellBot:
    def __init__(self, driver, db_path="accounts.sqlite"):
        self.driver = driver  # appium.webdriver.Remote, one per emulator instance
        self.email_service = EmailService()
        self.email_address: str | None = None
        self.debug_dir = "debug"
        self.db = Database(db_path)
        os.makedirs(self.debug_dir, exist_ok=True)

    # -- low level helpers ----------------------------------------------

    def _find_first(self, key: str, timeout: float = 10.0):
        """Try each candidate locator for `key` in order, return the first that appears.

        Runs inside a worker thread (via _run/run_in_executor), so this must not
        touch the asyncio event loop -- use the plain monotonic clock instead.
        """
        candidates = SELECTORS[key]
        deadline = time.monotonic() + timeout
        last_err = None
        while time.monotonic() < deadline:
            for by, value in candidates:
                try:
                    el = self.driver.find_element(by, value)
                    if el.is_displayed():
                        return el
                except NoSuchElementException as e:
                    last_err = e
                    continue
            time.sleep(0.3)
        raise ElementNotFound(
            f"None of the locators for '{key}' matched. Selectors are unverified placeholders -- "
            f"open Appium Inspector against a booted emulator to capture the real ones. ({last_err})"
        )

    async def _run(self, fn, *args):
        """Run a blocking Appium/Selenium call in a thread so we don't block the event loop."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, fn, *args)

    async def _find(self, key: str, timeout: float = 10.0):
        return await self._run(lambda: self._find_first(key, timeout))

    async def _tap(self, key: str, timeout: float = 10.0):
        el = await self._find(key, timeout)
        await self._run(el.click)
        return el

    def _type_human(self, el, text: str):
        # send_keys(text) in one shot is a request-timing tell, same as
        # instant-fill was on the Playwright branch. Send char-by-char with
        # jitter instead, mirroring the old press_sequentially(delay=...) use.
        for ch in text:
            el.send_keys(ch)
            time.sleep(random.uniform(0.05, 0.15))

    async def _type(self, key: str, text: str, timeout: float = 10.0):
        el = await self._find(key, timeout)
        await self._run(el.clear)
        await self._run(lambda: self._type_human(el, text))
        return el

    # -- account/email plumbing (unchanged, transport-agnostic) ---------

    async def get_code_for_existing_account(self, email: str) -> str:
        account = self.db.get_account(email)
        if not account or not account.get('email_password'):
            raise Exception(f"No email password found for {email}")

        if self.email_service.login(email, account['email_password']):
            code = await self.wait_for_verification_code()
            self.db.mark_account_used(email)
            return code
        else:
            raise Exception(f"Failed to login to email account for {email}")

    async def get_email(self, first_name="Taco", last_name="Lover") -> str:
        self.email_address = self.email_service.get_email()

        self.db.save_account(
            email=self.email_address,
            email_password=self.email_service.session_id,
            first_name=first_name,
            last_name=last_name,
            used=False
        )
        logger.info(f"Placeholder account for {self.email_address} saved to database.")

        return self.email_address or ""

    async def wait_for_verification_code(self) -> str:  # BLOCKING CALL!! Polls for verification code
        loop = asyncio.get_event_loop()
        code = await loop.run_in_executor(None, self.email_service.wait_for_verification_code)
        return code

    # -- app automation ---------------------------------------------------

    async def start(self):
        """Emulator/app is already booted and launched by emulator_manager by the time
        we get here (app_package/app_activity in the Appium capabilities). Just dismiss
        any first-run interstitials that block the sign-up entry point."""
        try:
            await self._tap("cookie_agree_button", timeout=3)
        except ElementNotFound:
            pass

    async def navigate_to_signup(self):
        logger.info("Tapping into sign-up flow...")
        await self._tap("sign_up_entry", timeout=20)
        await asyncio.sleep(random.uniform(1, 2))

    async def fill_registration_form(self, user_details: dict):
        email = user_details.get('email') or self.email_address
        logger.info(f"Inputting email for: {email}")

        await self._type("email_input", email, timeout=10)
        await asyncio.sleep(random.uniform(0.5, 1.5))
        await self._tap("confirm_email_button", timeout=10)

        logger.info("Email submitted. Waiting for verification-code screen...")
        try:
            await self._find("code_input", timeout=30)
            logger.info("Successfully reached verification step.")
        except ElementNotFound:
            logger.error("Timed out waiting for the verification-code screen.")
            raise Exception("Registration hung or failed to transition.")

    async def complete_signup(self, user_details: dict, verification_code: str):
        email = user_details.get("email") or self.email_address
        if not email:
            raise Exception("Email address not found for completion.")

        logger.info(f"Entering verification code for {email}: {verification_code}")
        await self._type("code_input", verification_code, timeout=10)
        await asyncio.sleep(random.uniform(0.5, 1.5))
        await self._tap("confirm_code_button", timeout=10)

        logger.info("Verification code submitted. Waiting for details form...")
        await asyncio.sleep(3)

        try:
            first_name = user_details.get("first_name", "Taco")
            last_name = user_details.get("last_name", "Lover")

            await self._type("first_name_input", first_name, timeout=10)
            logger.info("Filled First Name.")

            try:
                await self._type("last_name_input", last_name, timeout=5)
                logger.info("Filled Last Name.")
            except ElementNotFound:
                pass

            try:
                await self._type("password_input", user_details.get("password", "TacoBell123!"), timeout=5)
                logger.info("Filled Password.")
            except ElementNotFound:
                pass

            try:
                await self._type("zip_input", user_details.get("zip_code", "90210"), timeout=5)
                logger.info("Filled Zip.")
            except ElementNotFound:
                pass

            try:
                await self._tap("terms_checkbox", timeout=5)
                logger.info("Checked terms checkbox.")
            except ElementNotFound:
                pass

            await self._tap("create_account_button", timeout=10)
            logger.info("Details submitted. Waiting for final transition...")
            await asyncio.sleep(5)

        except ElementNotFound as e:
            logger.warning(f"Details form inputs not found or interaction failed: {e}")

        success = self.db.update_account(
            email=email,
            first_name=user_details.get("first_name", "Taco"),
            last_name=user_details.get("last_name", "Lover"),
            password=user_details.get("password", "TacoBell123!")
        )

        if success:
            logger.info(f"Account {email} successfully updated in database.")
        else:
            logger.warning(f"Account {email} could not be updated in database.")

        print(f"REGISTRATION COMPLETE: {email}")
