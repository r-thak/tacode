import asyncio
import os
import logging
from dotenv import load_dotenv

load_dotenv()
from bot import TacoBellBot
from emulator_manager import acquire_emulator, release_emulator

os.makedirs("debug", exist_ok=True)
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler("debug/bot.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


async def run():
    emu = None
    db_path = "accounts.sqlite"
    try:
        emu = await acquire_emulator()
        bot = TacoBellBot(emu.driver, db_path=db_path)
        await bot.start()

        max_retries = 3
        for attempt in range(max_retries):
            logger.info(f"Registration attempt {attempt + 1}/{max_retries}")
            try:
                email = await bot.get_email()

                await bot.navigate_to_signup()
                await bot.fill_registration_form({
                    "email": email
                })

                logger.info("Checking inbox for verification email...")
                code = await bot.wait_for_verification_code()
                logger.info(f"VERIFICATION CODE: {code}")

                await bot.complete_signup({
                    "first_name": "Taco",
                    "last_name": "Lover",
                    "password": "SecurePassword123!"
                }, code)

                break

            except Exception as e:
                logger.error(f"Attempt {attempt + 1} failed: {e}")
                if attempt < max_retries - 1:
                    logger.info("Retrying with a new emulator instance...")
                    await release_emulator(emu)
                    emu = None  # released -- don't let the outer finally double-release
                    await asyncio.sleep(5)
                    emu = await acquire_emulator()
                    bot = TacoBellBot(emu.driver, db_path=db_path)
                    await bot.start()
                else:
                    logger.error("All registration attempts failed.")
    finally:
        if emu:
            await release_emulator(emu)
        logger.info("Bot session finished.")


if __name__ == "__main__":
    asyncio.run(run())
