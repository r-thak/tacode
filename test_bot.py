import asyncio
from playwright.async_api import async_playwright
import os
import sys
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))
from dotenv import load_dotenv
load_dotenv()
from src.bot import TacoBellBot

async def main():
    async with async_playwright() as p:
        browser = await p.firefox.launch(
            headless=True,
            firefox_user_prefs={
                "dom.webdriver.enabled": False,
                "useAutomationExtension": False,
                "media.peerconnection.enabled": False,
            }
        )
        context = await browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) Gecko/20100101 Firefox/123.0",
            locale='en-US',
            timezone_id='America/New_York',
            permissions=['geolocation'],
            geolocation={'latitude': 40.7128, 'longitude': -74.0060},
            ignore_https_errors=True
        )
        bot = TacoBellBot(context, db_path="accounts.sqlite")
        await bot.start()
        
        email = await bot.get_email()
        print(f"Generated email: {email}")
        
        await bot.navigate_to_signup()
        await bot.fill_registration_form({"email": email})
        
        code = await bot.wait_for_verification_code()
        print(f"Code received: {code}")
        
        await bot.complete_signup({"first_name": "Test", "last_name": "User", "email": email}, code)
        
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
