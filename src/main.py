import asyncio
import os
import logging
import random
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()
from playwright.async_api import async_playwright
from bot import TacoBellBot
from playwright_stealth import stealth_async

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
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                '--disable-blink-features=AutomationControlled',
                '--no-sandbox',
                '--disable-setuid-sandbox'
            ]
        )
        
        iphone_13 = p.devices['iPhone 13']
        context = await browser.new_context(
            **iphone_13,
            locale='en-US',
            timezone_id='America/New_York',
            permissions=['geolocation'],
            geolocation={'latitude': 40.7128, 'longitude': -74.0060}
        )
        
        await context.route("**/*{fullstory,google-analytics,doubleclick,hotjar,segment}*", lambda route: route.abort())
        
        bot = TacoBellBot(context)
        await bot.start()
        
        width = iphone_13['viewport']['width'] + random.randint(-10, 10)
        height = iphone_13['viewport']['height'] + random.randint(-10, 10)
        await bot.page.set_viewport_size({"width": width, "height": height})
        
        await stealth_async(bot.page)
        
        try:
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
                        logger.info("Retrying with a new email...")
                        await asyncio.sleep(5)
                    else:
                        logger.error("All registration attempts failed.")
        
        finally:
            await browser.close()
            logger.info("Bot session finished.")

if __name__ == "__main__":
    asyncio.run(run())
