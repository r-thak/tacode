import asyncio
import os
import logging
from playwright.async_api import async_playwright
from bot import TacoBellBot
from playwright_stealth import stealth_async

# Configure logging
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
    ua = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36'
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent=ua,
            viewport={'width': 1280, 'height': 720},
            locale='en-US'
        )
        
        bot = TacoBellBot(context)
        await bot.start()
        await stealth_async(bot.page)
        
        try:
            # 1. Get temporary email
            email = await bot.get_email()
            
            # 2. Start registration
            await bot.navigate_to_signup()
            await bot.fill_registration_form({
                "email": email
            })
            
            # 3. Wait for verification code
            logger.info("Checking inbox for verification email...")
            try:
                code = await bot.wait_for_verification_code()
                logger.info(f"VERIFICATION CODE: {code}")
                
                # 4. Complete signup
                await bot.complete_signup({
                    "first_name": "Taco",
                    "last_name": "Lover",
                    "password": "SecurePassword123!"
                }, code)
                
            except Exception as e:
                logger.error(f"Email verification failed: {e}")
            
        except Exception as e:
            logger.error(f"An error occurred: {e}")
        
        finally:
            await browser.close()
            logger.info("Bot session finished.")

if __name__ == "__main__":
    asyncio.run(run())
