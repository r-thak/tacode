"""
Lifecycle management for a fresh Android emulator instance per registration.

Each call to acquire_emulator() boots a brand-new AVD process with a wiped
data partition (fresh Android ID / no leftover app state), waits for it to
finish booting, and hands back the ADB serial + a ready-to-use Appium
WebDriver session pointed at that device. release_emulator() tears the
session and the emulator process down.

This intentionally does NOT run inside Docker: the emulator needs hardware
acceleration (HVF on macOS / KVM on Linux) that isn't available to a
container on macOS. Run the FastAPI server directly on the host where the
emulator boots. See README.md for setup.
"""
import asyncio
import logging
import os
import socket
import time

from appium import webdriver
from appium.options.android import UiAutomator2Options

logger = logging.getLogger(__name__)

ANDROID_HOME = os.environ.get("ANDROID_HOME") or os.environ.get("ANDROID_SDK_ROOT") or os.path.expanduser("~/Library/Android/sdk")
EMULATOR_BIN = os.path.join(ANDROID_HOME, "emulator", "emulator")
ADB_BIN = os.path.join(ANDROID_HOME, "platform-tools", "adb")

AVD_NAME = os.environ.get("TACOBELL_AVD_NAME", "tacobell_base")
APPIUM_SERVER_URL = os.environ.get("APPIUM_SERVER_URL", "http://127.0.0.1:4723")
# Directory containing the split APKs to install (base.apk + one arch split +
# one density split + one language split -- see README.md "Get the APK").
# Appium's `app` capability can't install split APKs, so these get installed
# directly via `adb install-multiple` before the Appium session attaches.
TACOBELL_APK_DIR = os.environ.get("TACOBELL_APK_DIR")
TACOBELL_APP_PACKAGE = os.environ.get("TACOBELL_APP_PACKAGE", "com.tacobell.ordering")
# Verified against a real APK (version 8.90.2) booted on this AVD -- not a guess.
TACOBELL_APP_ACTIVITY = os.environ.get("TACOBELL_APP_ACTIVITY", "com.tacobell.splash.SplashActivity")

BOOT_TIMEOUT_S = 120
# Only one emulator instance runs at a time (one AVD, reused + wiped between
# registrations). Bump this by giving each slot its own AVD copy + port if
# you need real concurrency.
_emulator_lock = asyncio.Lock()


def _free_port() -> int:
    # Emulator console ports must be even; adb serial is port+1.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    return port - (port % 2)


class Emulator:
    def __init__(self, serial: str, port: int, process: asyncio.subprocess.Process):
        self.serial = serial
        self.port = port
        self.process = process
        self.driver: "webdriver.Remote | None" = None


async def _run(*args) -> tuple[int, str, str]:
    proc = await asyncio.create_subprocess_exec(*args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    out, err = await proc.communicate()
    return proc.returncode, out.decode(errors="ignore"), err.decode(errors="ignore")


async def _wait_for_boot(serial: str, timeout: int = BOOT_TIMEOUT_S):
    await _run(ADB_BIN, "-s", serial, "wait-for-device")

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        rc, out, _ = await _run(ADB_BIN, "-s", serial, "shell", "getprop", "sys.boot_completed")
        if out.strip() == "1":
            return
        await asyncio.sleep(2)
    raise TimeoutError(f"Emulator {serial} did not finish booting within {timeout}s")


async def _install_app(serial: str):
    """Install the split APKs via `adb install-multiple` (Appium's `app`
    capability can only take a single APK, not a split set). The AVD is
    wiped every boot, so this runs on every acquire_emulator() call --
    there's no persistent install to fall back on."""
    if not TACOBELL_APK_DIR or not os.path.isdir(TACOBELL_APK_DIR):
        rc, out, _ = await _run(ADB_BIN, "-s", serial, "shell", "pm", "path", TACOBELL_APP_PACKAGE)
        if rc == 0 and out.strip().startswith("package:"):
            return  # somehow already installed (e.g. baked into the AVD image) -- fine
        raise RuntimeError(
            f"TACOBELL_APK_DIR is not set to a real directory, and "
            f"{TACOBELL_APP_PACKAGE} isn't installed on this AVD (it's "
            f"freshly wiped every run, so nothing persists between calls). "
            f"Set TACOBELL_APK_DIR in .env to a folder containing base.apk + "
            f"the matching split APKs -- see README.md."
        )

    apks = sorted(
        os.path.join(TACOBELL_APK_DIR, f)
        for f in os.listdir(TACOBELL_APK_DIR)
        if f.endswith(".apk")
    )
    if not apks:
        raise RuntimeError(f"No .apk files found in TACOBELL_APK_DIR ({TACOBELL_APK_DIR}).")

    rc, out, err = await _run(ADB_BIN, "-s", serial, "install-multiple", "-r", *apks)
    if rc != 0 or "Success" not in out:
        raise RuntimeError(f"adb install-multiple failed: {out}\n{err}")
    logger.info(f"Installed {len(apks)} split APK(s) from {TACOBELL_APK_DIR} on {serial}.")


async def acquire_emulator() -> Emulator:
    """Boot a freshly-wiped emulator and return it with a live Appium session attached."""
    await _emulator_lock.acquire()
    try:
        if not os.path.exists(EMULATOR_BIN):
            raise RuntimeError(
                f"Android emulator binary not found at {EMULATOR_BIN}. "
                "Set ANDROID_HOME or run scripts/setup_emulator.sh first."
            )

        port = _free_port()
        serial = f"emulator-{port}"
        logger.info(f"Booting {AVD_NAME} on {serial} (wiped data)...")

        process = await asyncio.create_subprocess_exec(
            EMULATOR_BIN,
            "-avd", AVD_NAME,
            "-port", str(port),
            "-wipe-data",
            "-no-window",
            "-no-audio",
            "-no-boot-anim",
            "-no-snapshot-save",
            "-gpu", "swiftshader_indirect",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )

        emu = Emulator(serial=serial, port=port, process=process)

        try:
            await _wait_for_boot(serial)
            logger.info(f"{serial} booted.")

            # MANDATORY, not a nicety: a freshly-wiped AVD comes up with
            # persist.sys.timezone=America/Chicago, and the app crashes at
            # TacobellApplication.onCreate() via a Joda-Time
            # "datetime zone id 'America/Chicago' is not recognised" error on
            # this system image -- the app never gets past a WebView crash
            # loop without this. `setprop persist.sys.timezone` fails (the
            # property is read-only on this image); the alarm service call is
            # what actually sticks.
            await _run(ADB_BIN, "-s", serial, "shell", "service", "call", "alarm", "3", "s16", "UTC")

            await _install_app(serial)

            options = UiAutomator2Options()
            options.platform_name = "Android"
            options.udid = serial
            options.app_package = TACOBELL_APP_PACKAGE
            options.app_activity = TACOBELL_APP_ACTIVITY
            # App is already installed via adb install-multiple above --
            # Appium can't install split APKs itself, so no `app` capability
            # here. no_reset=True means "don't wipe app data before
            # attaching" (the whole AVD was already wiped at boot).
            options.no_reset = True
            options.auto_grant_permissions = True
            options.new_command_timeout = 120

            loop = asyncio.get_event_loop()
            emu.driver = await loop.run_in_executor(
                None, lambda: webdriver.Remote(APPIUM_SERVER_URL, options=options)
            )
            return emu
        except Exception:
            await _teardown(emu)
            raise
    except Exception:
        _emulator_lock.release()
        raise


async def _teardown(emu: Emulator):
    if emu.driver:
        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, emu.driver.quit)
        except Exception as e:
            logger.warning(f"Error quitting Appium session for {emu.serial}: {e}")

    try:
        await _run(ADB_BIN, "-s", emu.serial, "emu", "kill")
    except Exception:
        pass

    try:
        await asyncio.wait_for(emu.process.wait(), timeout=30)
    except asyncio.TimeoutError:
        logger.warning(f"{emu.serial} did not exit cleanly, killing process.")
        emu.process.kill()


async def release_emulator(emu: Emulator):
    """Tear down the Appium session + emulator process and free the slot."""
    try:
        await _teardown(emu)
    finally:
        _emulator_lock.release()
