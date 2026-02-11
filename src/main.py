import asyncio
from playwright.async_api import async_playwright
from bot import TacoBellBot
from playwright_stealth import stealth_async

async def run():
    # Use Firefox UA
    ua = 'Mozilla/5.0 (X11; Linux x86_64; rv:121.0) Gecko/20100101 Firefox/121.0'
    
    async with async_playwright() as p:
        # Launch browser with arguments
        browser = await p.firefox.launch(
            headless=True,
            args=[
                # Firefox doesn't support --disable-blink-features
                # Use preferences if needed, but playwright-stealth might not cover it fully
            ]
        )
        context = await browser.new_context(
            user_agent=ua,
            viewport={'width': 1280, 'height': 720},
            locale='en-US'
        )
        
        bot = TacoBellBot(context)
        await bot.start()
        
        # Apply stealth to the page
        await stealth_async(bot.page)
        
        # simulated flow
        await bot.navigate_to_signup()
        await bot.fill_registration_form({
            "first_name": "Taco",
            "last_name": "Lover",
            "email": "tacolover@example.com",
            "password": "securepassword123"
        })
        await bot.submit_registration()
        
        await browser.close()
        print("Bot finished.")

if __name__ == "__main__":
    asyncio.run(run())
