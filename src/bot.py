from playwright.async_api import Page, BrowserContext

class TacoBellBot:
    def __init__(self, context: BrowserContext):
        self.context = context
        self.page: Page | None = None

    async def start(self):
        """Initializes the page."""
        self.page = await self.context.new_page()
        # Set viewport size for consistent screenshots
        await self.page.set_viewport_size({"width": 1280, "height": 720})
        
        # Listen for console logs
        self.page.on("console", lambda msg: print(f"Browser Console: {msg.text}"))
        self.page.on("pageerror", lambda exc: print(f"Browser Error: {exc}"))
        self.page.on("requestfailed", lambda req: print(f"Request Failed: {req.url} - {req.failure}"))
        self.page.on("response", lambda res: print(f"Response: {res.status} {res.url}") if res.status >= 400 else None)

    async def navigate_to_signup(self):
        """Navigates to the signup page."""
        if not self.page:
            raise Exception("Page not initialized. Call start() first.")
        
        # Direct link found from page source inspection
        url = "https://www.tacobell.com/register/yum"
        print(f"Navigating to {url}...")
        
        try:
            # Increase timeout for initial load as real sites can be slow/heavy
            await self.page.goto(url, timeout=60000)
            await self.page.wait_for_load_state("networkidle")
            
            title = await self.page.title()
            print(f"Signup page loaded. Title: {title}")

        except Exception as e:
            print(f"Error navigating to signup: {e}")
            await self.page.screenshot(path="navigation_error.png")
            raise
            
    async def handle_cookie_banner(self):
        """Clicks Agree on the cookie banner if present."""
        print("Checking for cookie banner...")
        try:
            # Selector for the Agree button in the consent manager
            agree_button = self.page.locator("button:has-text('AGREE')").first
            if await agree_button.is_visible(timeout=5000):
                await agree_button.click()
                print("Clicked AGREE on cookie banner.")
                # Wait a bit for overlay to disappear
                await self.page.wait_for_timeout(1000)
            else:
                print("Cookie banner not found or not visible.")
        except Exception as e:
            print(f"Cookie banner check ignored: {e}")

    async def fill_registration_form(self, user_details: dict):
        """Fills the registration form with provided details."""
        if not self.page:
            raise Exception("Page not initialized.")

        # Handle cookies before interacting
        await self.handle_cookie_banner()

        email = user_details.get('email')
        print(f"Filling form for user: {email}")
        
        # Step 1: Enter Email
        try:
            # Simulate human typing
            email_input = self.page.locator("input[name='email']")
            await email_input.click()
            await self.page.wait_for_timeout(500)
            await email_input.press_sequentially(email, delay=100)
            print("Email field typed.")
            await self.page.wait_for_timeout(500)
        except Exception as e:
            print(f"Failed to fill email: {e}")
            await self.page.screenshot(path="email_fill_fail.png")
            raise

        # Wait for the Confirm button
        print("Waiting for Confirm button...")
        try:
            # Try pressing Enter first
            await self.page.keyboard.press("Enter")
            print("Pressed Enter.")
            
            # Check if navigation happened or button clicked
            # ...
            
        except Exception as e:
            print(f"Failed to submit: {e}")
            await self.page.screenshot(path="confirm_fail.png")
            raise

        # Wait for navigation or next step content
        print("Waiting for next step...")
        try:
            # Wait for email input to disappear or something new to key off
            # For now, just wait a bit longer and capture state
            await self.page.wait_for_timeout(5000) 
            # await self.page.wait_for_load_state("networkidle")
        except Exception as e:
            print(f"Wait failed: {e}")

        # Capture Screenshot of Step 2 state
        await self.page.screenshot(path="step2_state.png")
        print("Step 2 screenshot saved to step2_state.png")
        
        # Dump content of the next step
        content = await self.page.content()
        with open("page_source_step2.html", "w", encoding="utf-8") as f:
            f.write(content)
        print("Step 2 source saved to page_source_step2.html")
        
        # Check for Password field or Name inputs
        text = await self.page.inner_text("body")
        print(f"Step 2 Page text beginning: {text[:500]}...")
        
        inputs = await self.page.query_selector_all("input")
        print(f"Found {len(inputs)} input fields on Step 2 page.")
        for i, inp in enumerate(inputs):
            id_attr = await inp.get_attribute("id")
            name_attr = await inp.get_attribute("name")
            placeholder = await inp.get_attribute("placeholder")
            print(f"Step 2 Input {i}: id='{id_attr}', name='{name_attr}', placeholder='{placeholder}'")
        
    async def submit_registration(self):
        """Submits the registration form."""
        if not self.page:
            raise Exception("Page not initialized.")
            
        print("Submitting registration (simulated)...")
        # await self.page.click("button[type='submit']")
