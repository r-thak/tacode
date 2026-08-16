"""
Drives the real Taco Bell Android app via Appium/UiAutomator2.

The app ships Akamai Bot Manager's behavioral-biometrics SDK (BMP:* components
visible in logcat) which collects:
  - MotionManager:    accelerometer + gyroscope event counts and values
  - TouchManager:     touch duration, move vs updown event counts
  - TextChangeManager: per-keystroke timing intervals

Countermeasures (see akamai_evasion.py):
  1. Sensor stream (via emulator_manager.py): continuously feeds realistic
     accelerometer and gyroscope data into the AVD's virtual sensors via the
     emulator console telnet protocol, simulating a human holding a phone
     (gravity + tremor + slow drift + occasional reorientation). Verified
     working end-to-end at the emulator level (see README.md).
  2. Human-like taps (via akamai_evasion.HumanGesture): realistic 50-200ms
     touch duration instead of zero-duration instant taps, plus coordinate
     jitter.
  3. Typing via Appium's `mobile: type`, not send_keys -- two send_keys-based
     approaches were tried and live-tested broken (corrupted input, or valid
     text that never triggered the app's controlled-input state so the
     confirm button stayed disabled). See the comment on _type() below and
     README.md for the full story.

Verified live: the mobile:type fix makes confirm_button flip to enabled and
the tap actually advance the flow instead of no-opping (previously verified
broken on every prior run -- see _type()). What that submission does next is
NOT yet settled: one same-session run with a guerrillamail.com address (a
heavily blocklisted domain, see README) hit the app's error dialog; a
separate run with a real-domain address advanced past the modal with the
outcome unobserved (emulator torn down before capturing what it landed on).
A mail-domain rejection explains the one observed failure at least as well
as an Akamai behavioral-biometrics soft-block -- don't conclude BMP blocked
anything until a same-domain-as-a-known-good-run A/B is actually run and
captured. See _check_for_error_dialog().

What's calibrated below: the onboarding gauntlet, the sign-up modal through
submission, and the error dialog. Everything past submission (code entry,
details form) is still an educated guess -- re-verify live as the flow is
exercised further.
"""
import os
import logging
import asyncio
import random
import time
from concurrent.futures import ThreadPoolExecutor

from appium.webdriver.common.appiumby import AppiumBy
from selenium.common.exceptions import NoSuchElementException, StaleElementReferenceException

from email_service import EmailService
from database import Database
from akamai_evasion import HumanGesture

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
        # Dedicated single-thread executor for Playwright (sync API) calls.
        # Playwright's sync API requires all operations to run in the same
        # thread — the default executor may dispatch to different threads,
        # causing "Cannot switch to a different thread" errors.
        self._playwright_executor = ThreadPoolExecutor(max_workers=1)

    # -- low level helpers ----------------------------------------------

    async def _screenshot(self, label: str):
        """Save a screenshot to the debug directory for post-run analysis.

        Used at key flow points (after email submit, when waiting for screens,
        on errors) so we can see what the app is actually showing when things
        don't go as expected.
        """
        if not self.driver:
            return
        try:
            ts = time.strftime("%Y%m%d_%H%M%S")
            path = os.path.join(self.debug_dir, f"{ts}_{label}.png")
            await self._run(lambda: self.driver.save_screenshot(path))
            logger.info(f"Screenshot saved: {path}")
        except Exception as e:
            logger.warning(f"Failed to take screenshot ({label}): {e}")

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

    async def _tap(self, key: str, timeout: float = 10.0):
        """Tap an element with realistic human touch duration.

        BMP's TouchManager tracks touch duration and move vs updown event
        counts. An instantaneous clickGesture has zero duration — the SDK
        can detect that. Use HumanGesture.tap which creates a press with
        50-200ms hold duration (variable per tap), slight coordinate jitter,
        and a realistic pressure curve.
        """
        el = await self._find(key, timeout)
        rect = el.rect
        cx = rect['x'] + rect['width'] // 2
        cy = rect['y'] + rect['height'] // 2
        await HumanGesture.tap(self.driver, cx, cy)
        return el

    async def _type(self, key: str, text: str, timeout: float = 10.0):
        """Type text via Appium's `mobile: type`, not send_keys.

        Both plain bulk send_keys and char-by-char send_keys were tried and
        live-tested broken, for two different reasons:
        - char-by-char with inter-key delays (old HumanGesture.type_text, to
          defeat BMP's TextChangeManager keystroke-timing capture) corrupted
          the input outright on this app's React Native TextInput -- only
          the *last* character landed ("william@gmail.com" -> "m"). Each
          keystroke's native edit races the JS bridge's controlled-input
          round-trip (onChangeText -> setState -> re-render -> setText), and
          the artificial delay gave the stale re-render time to clobber the
          previous character every time.
        - plain bulk send_keys doesn't corrupt the text (it lands intact),
          but it sets the EditText's buffer via the accessibility
          ACTION_SET_TEXT action, which never fires a real TextWatcher/
          onChangeText event -- confirmed live via `enabled`/`clickable` on
          confirm_button: the field showed the correct text but the button
          stayed permanently disabled, because the app's controlled-input
          state never saw the change.
        `mobile: type` dispatches real Android KeyEvents instead, so
        onChangeText fires normally and the button enables. Verified live
        against the sign-up modal (see scratchpad test sweep) -- it's the
        only one of four strategies tried (mobile: type, oneKeyAtATime
        send_keys, bulk send_keys + backspace nudge, `adb shell input text`)
        that flips confirm_button to enabled=true.
        """
        el = await self._find(key, timeout)
        await self._run(el.clear)
        await self._run(el.click)
        await self._run(lambda: self.driver.execute_script("mobile: type", {"text": text}))
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

        Cause is deliberately left undetermined in the raised message: a
        live run submitting a guerrillamail.com address (heavily
        blocklisted, see README) hit this dialog, but a same-session run
        with a real-domain address advanced past the modal instead of
        hitting it -- so a mail-domain rejection fits the one observed
        failure at least as well as an Akamai behavioral-biometrics
        soft-block does. Don't assume BMP without a same-domain A/B."""
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
        await self._screenshot("error_dialog")
        raise RegistrationBlocked(
            f"Sign-up rejected by the app: {body!r}. Cause undetermined -- "
            f"could be a mail-domain blocklist rejection (the address' domain "
            f"may be blocklisted) or an Akamai behavioral-biometrics "
            f"soft-block despite the active evasion layer (sensor stream + "
            f"human-like tap gestures). Re-run with a non-blocklisted domain "
            f"to disambiguate before concluding which."
        )

    # -- account/email plumbing (unchanged, transport-agnostic) ---------

    async def get_code_for_existing_account(self, email: str) -> str:
        account = self.db.get_account(email)
        if not account or not account.get('email_password'):
            raise Exception(f"No email password found for {email}")

        loop = asyncio.get_event_loop()
        logged_in = await loop.run_in_executor(self._playwright_executor, self.email_service.login, email, account['email_password'])
        if logged_in:
            code = await self.wait_for_verification_code()
            self.db.mark_account_used(email)
            return code
        else:
            raise Exception(f"Failed to login to email account for {email}")

    async def get_email(self, first_name="Taco", last_name="Lover") -> str:
        # get_email() launches a real browser (smailpro/guerrillamail provider),
        # so don't block the event loop -- run it in the dedicated Playwright
        # thread (sync API requires same-thread affinity).
        loop = asyncio.get_event_loop()
        self.email_address = await loop.run_in_executor(self._playwright_executor, self.email_service.get_email)

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
        code = await loop.run_in_executor(self._playwright_executor, self.email_service.wait_for_verification_code)
        return code

    async def close(self):
        """Release the emulator-independent resources this bot owns (currently
        just the email service, which may hold an open browser). Call this in
        callers' finally blocks alongside emulator_manager.release_emulator."""
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(self._playwright_executor, self.email_service.close)

    # -- app automation ---------------------------------------------------

    async def start(self, timeout: float = 120.0):
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
        # Blur the email field so the confirm button enables. The header tap +
        # keyboard dismiss combination is the best-effort approach; the button
        # may stay disabled if the BMP SDK filters Appium input before the
        # evasion layer can mask it. The sensor stream + human gesture layer
        # aims to head this off, but this exact spot was flaky before evasion
        # was added -- re-verify live.
        await self._tap("signup_modal_header", timeout=5)
        await self._dismiss_keyboard()
        await asyncio.sleep(random.uniform(0.8, 1.8))
        await self._tap("confirm_email_button", timeout=10)

        logger.info("Email submitted. Checking for the app's error dialog first...")
        await self._screenshot("after_email_submit")
        await self._check_for_error_dialog()  # raises RegistrationBlocked if present

        logger.info("No error dialog. Waiting for verification-code screen...")
        try:
            await self._find("code_input", timeout=30)
            logger.info("Successfully reached verification step.")
        except ElementNotFound:
            await self._screenshot("no_code_screen_timeout")
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
