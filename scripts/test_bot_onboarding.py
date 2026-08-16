"""Test: boot emulator, run bot.start() (onboarding gauntlet), screenshot result.

Run from the repo root:  python scripts/test_bot_onboarding.py
"""
import asyncio
import logging
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("test_bot_start")

from emulator_manager import acquire_emulator, release_emulator, ADB_BIN
from bot import TacoBellBot


async def _run_cmd(*args):
    proc = await asyncio.create_subprocess_exec(*args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    out, err = await proc.communicate()
    return proc.returncode, out.decode(errors="ignore"), err.decode(errors="ignore")


async def main():
    emu = None
    try:
        emu = await acquire_emulator()
        logger.info(f"Emulator ready: {emu.serial}")

        bot = TacoBellBot(emu.driver, db_path="accounts.sqlite")
        logger.info("Running bot.start() (onboarding gauntlet)...")
        await bot.start(timeout=60)

        ts = time.strftime("%Y%m%d_%H%M%S")
        os.makedirs("debug", exist_ok=True)
        shot = os.path.join("debug", f"{ts}_after_start.png")
        await _run_cmd(ADB_BIN, "-s", emu.serial, "shell", "screencap", "-p", "/sdcard/after_start.png")
        await _run_cmd(ADB_BIN, "-s", emu.serial, "pull", "/sdcard/after_start.png", shot)
        logger.info(f"Screenshot saved: {shot}")

        from appium.webdriver.common.appiumby import AppiumBy
        present = emu.driver.find_elements(AppiumBy.ID, "com.tacobell.ordering:id/inboxSignUpTextView")
        logger.info(f"sign_up_entry present: {bool(present)}")

        if not present:
            src = emu.driver.page_source
            with open(os.path.join("debug", f"{ts}_page_source.xml"), "w") as f:
                f.write(src)
            logger.info(f"Page source dumped ({len(src)} chars)")

        return 0
    except Exception as e:
        logger.exception(f"FAILED: {e}")
        return 1
    finally:
        if emu:
            await release_emulator(emu)


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
