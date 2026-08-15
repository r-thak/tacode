import asyncio
import sys
import logging
from bot import TacoBellBot

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)
logger = logging.getLogger(__name__)

async def main():
    if len(sys.argv) < 2:
        print("Usage: python src/get_code.py <email>")
        return

    email = sys.argv[1]

    # No emulator needed: this only talks to the mailbox (may still open its
    # own browser under the hood if EMAIL_PROVIDER=guerrillamail).
    bot = TacoBellBot(None)

    try:
        logger.info(f"Attempting to retrieve code for {email}...")
        code = await bot.get_code_for_existing_account(email)
        print(f"\nSUCCESS! Verification code for {email}: {code}\n")
    except Exception as e:
        logger.error(f"Error: {e}")
    finally:
        await bot.close()

if __name__ == "__main__":
    asyncio.run(main())
