
import asyncio
from playwright.async_api import async_playwright
from bot import TacoBellBot
from playwright_stealth import Stealth

async def run():
    ua = 'Mozilla/5.0 (X11; Linux x86_64; rv:121.0) Gecko/20100101 Firefox/121.0'
    
    async with async_playwright() as p:
        browser = await p.firefox.launch(headless=True)
        context = await browser.new_context(
            user_agent=ua,
            viewport={'width': 1280, 'height': 720},
            locale='en-US'
        )
        
        bot = TacoBellBot(context)
        await bot.start()
        await Stealth().apply_stealth_async(bot.page)
        
        try:
            # 1. Get temporary email
            email = await bot.get_email()
            
            # 2. Start registration
            await bot.navigate_to_signup()
            await bot.fill_registration_form({
                "email": email
            })
            
            # 3. Wait for verification code
            print("Checking inbox for verification email...")
            try:
                code = await bot.wait_for_verification_code()
                print(f"VERIFICATION CODE: {code}")
                
                # 4. Complete signup
                await bot.complete_signup({
                    "first_name": "Taco",
                    "last_name": "Lover",
                    "password": "SecurePassword123!"
                }, code)
                
            except Exception as e:
                print(f"Email verification failed: {e}")
            
        except Exception as e:
            print(f"An error occurred: {e}")
        
        finally:
            await browser.close()
            print("Bot session finished.")

if __name__ == "__main__":
    asyncio.run(run())
