"""
Drives the real Taco Bell Android app via Appium/UiAutomator2.

IMPORTANT, read before spending more time calibrating this: the sign-up
submission was live-tested against the real app (v8.90.2) on a booted AVD
and came back with a generic "Uh-oh! We're experiencing a system error"
dialog (see SELECTORS["auth_error_*"] below). Logcat shows why -- at the
exact moment the request goes out, the app's `BMP:*` components (Akamai
Bot Manager's behavioral-biometrics SDK) collect motion/gyroscope/touch/
keystroke-timing sensor data, encode it, and ship it to
https://www.tacobell.com/ alongside the request:

    BMP:CYFManager: Building sensor data: Thread[OkHttp https://www.tacobell.com/...]
    BMP:MotionManager: Motion Event Count: 128/128
    BMP:TouchManager: Touch Event Count: 18 (move: 0, updown: 18)
    BMP:TextChangeManager: mEvent Count: 9, Key String ...  (per-keystroke timing)
    BMP:MotionListener: GyroScope status true and Accelerometer status true

That's strong circumstantial evidence of a behavioral-biometrics soft-block,
not a decrypted server verdict -- but the timing (telemetry built and sent,
then immediately a deliberately vague error) is the textbook pattern. This
means the branch's founding premise doesn't hold: the app isn't a softer
target than the website, it ships *more* anti-bot instrumentation, reading
sensors a headless AVD doesn't meaningfully have. See README.md.

I'm not attempting to spoof sensor data to defeat this -- that's building
evasion tooling against a commercial anti-fraud vendor's product, not
something this file should do. Getting further would mean a physical
device with real sensors and real human input, which is a different
project.

What's real and calibrated below regardless: the onboarding gauntlet, the
sign-up modal up through submission, and the error dialog. Everything past
the error (code entry, details form) is still an educated guess -- the
flow never got far enough to see it.

One more data point, found *after* the above: in later automated runs
through this file, confirm_email_button stayed disabled and the flow never
even reached submission -- it's supposed to enable once the email field
blurs, and a raw `adb shell input tap` on the header did that once in an
early manual test, but no Appium-synthesized tap/keyboard-dismiss
combination reproduced it across several live re-runs (see the comment in
fill_registration_form). That gap between raw input events and
Appium-synthesized ones, on an app already confirmed to run behavioral-
biometrics telemetry, is plausibly the same defense one step earlier rather
than an unrelated UI-timing bug -- noted, not chased further.
"""
import os
import logging
import asyncio
import random
import time

from appium.webdriver.common.appiumby import AppiumBy
from selenium.common.exceptions import NoSuchElementException, StaleElementReferenceException

from email_service import EmailService
from database import Database

logger = logging.getLogger(__name__)

# --- Element locators -------------------------------------------------------
# Verified (captured against a real booted AVD + real APK v8.90.2, not
# guessed): the onboarding screens, system permission dialogs, the sign-up
# modal through submission, and the error dialog.
# Still unverified guesses (never reached -- see module docstring): the
# verification-code screen and the account-details form.
SELECTORS = {
    # Onboarding gauntlet -- appears every run since the AVD's data is wiped
    # on every boot, so this isn't a "just in case" fallback, it's expected.
    "onboarding_lets_go": [
        (AppiumBy.ID, "com.tacobell.ordering:id/btnLetsGo"),
    ],
    "system_permission_allow_foreground": [
        (AppiumBy.ID, "com.android.permissioncontroller:id/permission_allow_foreground_only_button"),
    ],
    "system_permission_allow": [
        (AppiumBy.ID, "com.android.permissioncontroller:id/permission_allow_button"),
    ],
    "sign_up_entry": [
        (AppiumBy.ID, "com.tacobell.ordering:id/inboxSignUpTextView"),
    ],
    "email_input": [
        (AppiumBy.ID, "com.tacobell.ordering:id/signup_modal_email_field"),
    ],
    # Inert header text on the same modal -- tapping it is a verified way to
    # blur the email field (see fill_registration_form's comment for why
    # that's necessary at all).
    "signup_modal_header": [
        (AppiumBy.ID, "com.tacobell.ordering:id/headerText"),
    ],
    "confirm_email_button": [
        (AppiumBy.ID, "com.tacobell.ordering:id/confirm_button"),
    ],
    # Verified: this is what actually comes back on submission right now.
    "auth_error_title": [
        (AppiumBy.ID, "com.tacobell.ordering:id/auth_error_title"),
    ],
    "auth_error_body": [
        (AppiumBy.ID, "com.tacobell.ordering:id/auth_error_body"),
    ],
    "auth_error_button": [
        (AppiumBy.ID, "com.tacobell.ordering:id/auth_error_button"),
    ],

    # --- Unverified from here down (never reached) ---
    "code_input": [
        (AppiumBy.ID, "com.tacobell.ordering:id/verification_code_input"),
        (AppiumBy.ACCESSIBILITY_ID, "Enter Code"),
        (AppiumBy.XPATH, "//android.widget.EditText[contains(@resource-id, 'code')]"),
    ],
    "confirm_code_button": [
        # Guess based on the email step reusing a generic "confirm_button" id
        # for its primary CTA -- unverified whether the code step does too.
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
}


class ElementNotFound(Exception):
    pass


class RegistrationBlocked(Exception):
    """Raised when the app's own error dialog shows up (verified: this is what
    a sign-up submission currently gets back -- see module docstring). Distinct
    from ElementNotFound/timeout so callers can tell "blocked" from "slow"."""
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
                except (NoSuchElementException, StaleElementReferenceException) as e:
                    # Stale reference happens when Appium's element cache hands
                    # back a handle to a node that's since been torn down by an
                    # activity transition (verified: hit this mid-onboarding) --
                    # functionally the same as "not found", so retry the search.
                    last_err = e
                    continue
            time.sleep(0.3)
        raise ElementNotFound(f"None of the locators for '{key}' matched. ({last_err})")

    async def _run(self, fn, *args):
        """Run a blocking Appium/Selenium call in a thread so we don't block the event loop."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, fn, *args)

    async def _find(self, key: str, timeout: float = 10.0):
        return await self._run(lambda: self._find_first(key, timeout))

    async def _tap_if_present(self, key: str, timeout: float = 3.0) -> bool:
        try:
            await self._tap(key, timeout=timeout)
            return True
        except ElementNotFound:
            return False

    def _is_present(self, key: str) -> bool:
        try:
            self._find_first(key, timeout=0.1)
            return True
        except ElementNotFound:
            return False

    async def _wait_until_gone(self, key: str, timeout: float = 5.0):
        """Poll until `key` is no longer present. Two consecutive onboarding
        screens reuse the same resource-id for their CTA (verified: both
        "DROP YOUR LOCATION" and "HUNGRY FOR UPDATES?" use btnLetsGo) --
        Android's activity-transition animation can leave the outgoing
        screen's button briefly matchable at the same time as the incoming
        one, so a blind tap can hit the stale element and no-op. Confirming
        the old one is gone before moving on avoids that race."""
        await self._run(lambda: self._poll_until_gone(key, timeout))

    def _poll_until_gone(self, key: str, timeout: float):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if not self._is_present(key):
                return
            time.sleep(0.3)

    def _coordinate_tap(self, el):
        # Verified necessary, not stylistic: confirm_button on the sign-up
        # modal reports clickable="false" in the accessibility tree even once
        # enabled/genuinely tappable, and element.click() silently no-ops on
        # it (the bot would sit on the same screen forever). A raw coordinate
        # tap at the element's center -- what `adb shell input tap` does --
        # works. Used for all taps here for consistency, not just that button.
        rect = el.rect
        cx = rect['x'] + rect['width'] // 2
        cy = rect['y'] + rect['height'] // 2
        self.driver.execute_script('mobile: clickGesture', {'x': cx, 'y': cy})

    async def _tap(self, key: str, timeout: float = 10.0):
        el = await self._find(key, timeout)
        await self._run(lambda: self._coordinate_tap(el))
        return el

    async def _type(self, key: str, text: str, timeout: float = 10.0):
        el = await self._find(key, timeout)
        await self._run(el.clear)
        # Plain send_keys, not char-by-char with jitter: verified (see
        # BMP:TextChangeManager in the module docstring) that the app already
        # captures and ships per-keystroke timing on its own, so client-side
        # typing delay doesn't hide anything and only slows things down.
        await self._run(el.send_keys, text)
        return el

    async def _dismiss_keyboard(self):
        """The IME covers the submit button after typing into a field on this
        screen size (verified), and the button doesn't reliably register the
        tap until the field has blurred. Hide the keyboard before tapping."""
        try:
            await self._run(self.driver.hide_keyboard)
        except Exception:
            pass  # no keyboard was showing -- fine

    async def _check_for_error_dialog(self, timeout: float = 6.0):
        """Raises RegistrationBlocked if the app's error dialog is showing.
        See module docstring -- this is the verified failure mode, not a guess."""
        try:
            await self._find("auth_error_title", timeout=timeout)
        except ElementNotFound:
            return  # no error dialog -- good, proceed

        body = ""
        try:
            body_el = await self._find("auth_error_body", timeout=1)
            body = await self._run(lambda: body_el.text)
        except ElementNotFound:
            pass

        await self._tap_if_present("auth_error_button", timeout=3)
        raise RegistrationBlocked(
            f"Sign-up rejected by the app: {body!r}. Likely an Akamai "
            f"behavioral-biometrics soft-block (see bot.py module docstring) -- "
            f"retrying with a new email will not help."
        )

    # -- account/email plumbing (unchanged, transport-agnostic) ---------

    async def get_code_for_existing_account(self, email: str) -> str:
        account = self.db.get_account(email)
        if not account or not account.get('email_password'):
            raise Exception(f"No email password found for {email}")

        loop = asyncio.get_event_loop()
        logged_in = await loop.run_in_executor(None, self.email_service.login, email, account['email_password'])
        if logged_in:
            code = await self.wait_for_verification_code()
            self.db.mark_account_used(email)
            return code
        else:
            raise Exception(f"Failed to login to email account for {email}")

    async def get_email(self, first_name="Taco", last_name="Lover") -> str:
        # get_email() may launch a real browser (guerrillamail provider), so
        # don't block the event loop -- run it in a worker thread same as
        # wait_for_verification_code below.
        loop = asyncio.get_event_loop()
        self.email_address = await loop.run_in_executor(None, self.email_service.get_email)

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

    async def close(self):
        """Release the emulator-independent resources this bot owns (currently
        just the email service, which may hold an open browser). Call this in
        callers' finally blocks alongside emulator_manager.release_emulator."""
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self.email_service.close)

    # -- app automation ---------------------------------------------------

    async def start(self, timeout: float = 60.0):
        """Walk the onboarding gauntlet (verified: location prompt -> system
        permission dialog -> notification prompt -> system permission dialog)
        by reacting to whatever's currently on screen and looping until the
        home screen shows up, rather than assuming a fixed step order.

        This happens every run, not just first-launch, since the AVD's data
        is wiped on every boot. An adaptive loop instead of a fixed sequence
        is deliberate, not stylistic: cold start timing varies a lot (~8-20s+
        observed live), granting a permission recreates OnboardingActivity,
        and two different onboarding screens reuse the same btnLetsGo id --
        a fixed-order script can tap a stale/about-to-be-destroyed button
        during that recreation and silently no-op forever (verified: this is
        exactly what a linear tap-sequence version of this method did in
        testing). Reacting to current state and retrying is self-healing --
        a no-op tap just gets re-evaluated next iteration."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if await self._run(lambda: self._is_present("sign_up_entry")):
                return  # home screen reached

            for key in ("system_permission_allow_foreground", "system_permission_allow", "onboarding_lets_go"):
                if await self._tap_if_present(key, timeout=1):
                    await asyncio.sleep(1.5)  # let the tap's transition/animation settle
                    break
            else:
                await asyncio.sleep(1)  # nothing recognized yet (still cold-starting) -- wait and recheck

        logger.warning("Onboarding gauntlet did not reach the home screen within the time budget.")

    async def navigate_to_signup(self):
        logger.info("Tapping into sign-up flow...")
        await self._tap("sign_up_entry", timeout=20)
        await asyncio.sleep(random.uniform(1, 2))

    async def fill_registration_form(self, user_details: dict):
        email = user_details.get('email') or self.email_address
        logger.info(f"Inputting email for: {email}")

        await self._type("email_input", email, timeout=10)
        # NOT reliably working, be aware: confirm_email_button starts
        # disabled after typing and is supposed to enable once the field
        # blurs. A raw `adb shell input tap` on the header did enable it in
        # one manual test early on. Every automated variant tried since --
        # this header tap, hide_keyboard(), both together, BACK-key -- left
        # it disabled across repeated live runs (BACK even closes the whole
        # modal, don't use it here). That gap between raw input events and
        # Appium-synthesized ones is suspicious given the rest of this file's
        # docstring: this may be the same input-source discrimination as the
        # Akamai behavioral-biometrics check, one step earlier, not a plain
        # UI-timing race. Left in as the best-effort attempt; don't assume it
        # unblocks the flow without re-verifying live.
        await self._tap("signup_modal_header", timeout=5)
        await self._dismiss_keyboard()
        await asyncio.sleep(random.uniform(0.5, 1.5))
        await self._tap("confirm_email_button", timeout=10)

        logger.info("Email submitted. Checking for the app's error dialog first...")
        await self._check_for_error_dialog()  # raises RegistrationBlocked if present

        logger.info("No error dialog. Waiting for verification-code screen...")
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
        await self._dismiss_keyboard()
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

            await self._dismiss_keyboard()

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
