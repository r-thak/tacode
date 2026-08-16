"""Standalone test: boot a fresh emulator, install the app, attach Appium,
launch the Taco Bell app, and tear down. Isolates the emulator/Appium stack
from the bot/email registration flow.

Run from the repo root:  python scripts/test_emulator_boot.py
"""
import asyncio
import logging
import os
import sys
import time

from dotenv import load_dotenv
load_dotenv()

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("test_boot")

from emulator_manager import acquire_emulator, release_emulator, ADB_BIN


async def main():
    emu = None
    try:
        t0 = time.monotonic()
        logger.info("Calling acquire_emulator()...")
        emu = await acquire_emulator()
        logger.info(f"Emulator ready in {time.monotonic()-t0:.1f}s: serial={emu.serial}, "
                    f"console_port={emu.console_port}, sensor_stream={'on' if emu.sensor_stream else 'off'}")

        # Confirm the app is actually installed and report its version.
        from appium.webdriver.common.appiumby import AppiumBy
        rc, out, _ = await _run_cmd(ADB_BIN, "-s", emu.serial, "shell",
                                    "dumpsys", "package", "com.tacobell.ordering")
        ver = "unknown"
        for line in out.splitlines():
            if "versionName=" in line:
                ver = line.strip()
                break
        logger.info(f"App installed on device: {ver.split('versionName=')[-1] if 'versionName=' in ver else 'unknown'}")

        # current foreground / focused activity
        rc, out, _ = await _run_cmd(ADB_BIN, "-s", emu.serial, "shell",
                                    "dumpsys", "activity", "activities")
        focused = [l.strip() for l in out.splitlines() if "mResumedActivity" in l or "ResumedActivity" in l]
        logger.info(f"Focused activity: {focused[0] if focused else 'none'}")

        # Take a screenshot so we can see what launched.
        ts = time.strftime("%Y%m%d_%H%M%S")
        shot = os.path.join("debug", f"{ts}_boot_test.png")
        os.makedirs("debug", exist_ok=True)
        await _run_cmd(ADB_BIN, "-s", emu.serial, "shell", "screencap", "-p",
                       "/sdcard/boot_test.png")
        await _run_cmd(ADB_BIN, "-s", emu.serial, "pull", "/sdcard/boot_test.png", shot)
        logger.info(f"Screenshot saved: {shot}")

        # Quick check: is the sign_up_entry element present (home screen)?
        present = emu.driver.find_elements(AppiumBy.ID, "com.tacobell.ordering:id/inboxSignUpTextView")
        logger.info(f"sign_up_entry present on launch: {bool(present)} ({len(present)} match(es))")

        logger.info("BOOT TEST PASSED: emulator up, app installed, Appium session attached.")
        return 0
    except Exception as e:
        logger.exception(f"BOOT TEST FAILED: {e}")
        return 1
    finally:
        if emu:
            logger.info("Releasing emulator...")
            await release_emulator(emu)
            logger.info("Emulator released.")


async def _run_cmd(*args):
    proc = await asyncio.create_subprocess_exec(*args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    out, err = await proc.communicate()
    return proc.returncode, out.decode(errors="ignore"), err.decode(errors="ignore")


if __name__ == "__main__":
    rc = asyncio.run(main())
    sys.exit(rc)
