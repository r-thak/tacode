import asyncio
from playwright.async_api import async_playwright
import random

async def main():
    async with async_playwright() as p:
        browser = await p.firefox.launch(headless=True)
        context = await browser.new_context(viewport={"width": 1920, "height": 1080})
        page = await context.new_page()
        try:
            print("Navigating...")
            await page.goto("https://www.google.com")
            await page.goto("https://www.tacobell.com/register/yum", wait_until="load", referer="https://www.tacobell.com/")
            print("On signup page...")
            email_input = page.locator("input[name='email']")
            await email_input.wait_for(state="visible", timeout=15000)
            await email_input.click()
            await email_input.press_sequentially(f"test{random.randint(10000,99999)}@gmail.com", delay=100)
            
            confirm = page.locator("button:has-text('CONFIRM')").first
            await confirm.click()
            print("Clicked confirm")
            
            try:
                await page.wait_for_selector("text=Verify Your Email", timeout=15000)
                print("Success!")
            except Exception as e:
                print("Failed to verify:", e)
                # await page.screenshot(path="test2_failed.png")
            
        finally:
            await browser.close()

asyncio.run(main())
