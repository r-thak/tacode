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
TACOBELL_APK_PATH = os.environ.get("TACOBELL_APK_PATH")  # only needed the first time the AVD doesn't have the app
TACOBELL_APP_PACKAGE = os.environ.get("TACOBELL_APP_PACKAGE", "com.tacobell.ordering")
# Leave unset by default: when `app` (the APK path) is provided, Appium can
# auto-detect the launchable activity from the package manifest, which is
# more reliable than guessing the activity class name here.
TACOBELL_APP_ACTIVITY = os.environ.get("TACOBELL_APP_ACTIVITY") or None

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

            options = UiAutomator2Options()
            options.platform_name = "Android"
            options.udid = serial
            options.app_package = TACOBELL_APP_PACKAGE
            if TACOBELL_APP_ACTIVITY:
                options.app_activity = TACOBELL_APP_ACTIVITY
            options.no_reset = False
            options.full_reset = False
            options.auto_grant_permissions = True
            options.new_command_timeout = 120
            if TACOBELL_APK_PATH and os.path.exists(TACOBELL_APK_PATH):
                # Installs (or reinstalls) the APK before launching. Skip this
                # if the AVD's snapshot/image already has the app baked in.
                options.app = TACOBELL_APK_PATH

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
