import asyncio
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        browser = await p.firefox.launch(
            headless=True,
        )
        context = await browser.new_context(
            viewport={"width": 1920, "height": 1080},
        )
        page = await context.new_page()
        try:
            print("Navigating...")
            await page.goto("https://www.tacobell.com/", wait_until="domcontentloaded", timeout=15000)
            print("Success")
            await page.screenshot(path="test_tb.png")
        except Exception as e:
            print(f"Error: {e}")
        finally:
            await browser.close()

asyncio.run(main())
