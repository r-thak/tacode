
from playwright.async_api import Page, BrowserContext
import asyncio
from email_service import EmailService

class TacoBellBot:
    def __init__(self, context: BrowserContext):
        self.context = context
        self.page: Page | None = None
        self.email_service = EmailService()
        self.email_address: str | None = None

    async def start(self):
        """Initializes the browser page."""
        self.page = await self.context.new_page()
        await self.page.set_viewport_size({"width": 1280, "height": 720})

    async def get_email(self) -> str:
        """Retrieves a temporary email address."""
        self.email_address = self.email_service.get_email()
        return self.email_address

    async def navigate_to_signup(self):
        """Navigates to the signup page."""
        if not self.page:
            raise Exception("Page not initialized.")
        
        url = "https://www.tacobell.com/register/yum"
        print(f"Navigating to {url}...")
        await self.page.goto(url, timeout=60000)
        await self.page.wait_for_load_state("networkidle")

    async def handle_cookie_banner(self):
        """Clicks Agree on the cookie banner if present."""
        try:
            agree_button = self.page.locator("button:has-text('AGREE')").first
            if await agree_button.is_visible(timeout=5000):
                await agree_button.click()
                print("Clicked AGREE on cookie banner.")
                await self.page.wait_for_timeout(1000)
        except Exception:
            pass

    async def fill_registration_form(self, user_details: dict):
        """Fills the initial registration form."""
        if not self.page:
            raise Exception("Page not initialized.")

        await self.handle_cookie_banner()

        email = user_details.get('email') or self.email_address
        print(f"Filling form for: {email}")
        
        try:
            # Enter Email
            email_input = self.page.locator("input[name='email']")
            await email_input.wait_for(state="visible", timeout=10000)
            await email_input.click()
            await email_input.fill("") # Clear just in case
            await email_input.press_sequentially(email, delay=100)
            
            # Click Confirm button (more reliable than just pressing Enter)
            confirm_button = self.page.locator("button:has-text('CONFIRM')").first
            await confirm_button.wait_for(state="visible", timeout=5000)
            await confirm_button.click()
            
            print("Email submitted. Waiting for page transition...")
            
            # Wait for success - usually transitions to "Verify Your Email"
            # Or at least wait for the loading indicator to disappear/new content to appear
            try:
                await self.page.wait_for_selector("text=Verify Your Email", timeout=30000)
                print("Successfully reached verification step.")
            except Exception:
                # If it didn't find the text, maybe it's still loading or showed an error
                print("Could not confirm 'Verify Your Email' text. Checking for errors...")
                await self.page.screenshot(path="registration_transition_check.png")
                # Check if we are still on the same page but it's not loading anymore
                # or if a different message appeared.

            await self.page.screenshot(path="registration_step2.png")

        except Exception as e:
            print(f"Registration failed at email step: {e}")
            await self.page.screenshot(path="registration_error.png")
            raise

    async def wait_for_verification_code(self) -> str:
        """Polls for the verification email and extracts the code."""
        # This uses the EmailService which calls the 1secmail API
        # We wrap it in to_thread because it's a blocking requests call
        loop = asyncio.get_event_loop()
        code = await loop.run_in_executor(None, self.email_service.wait_for_verification_code)
        return code

    async def complete_signup(self, user_details: dict, verification_code: str):
        """Enters the verification code and other details (simulated)."""
        print(f"Completing signup with verification code: {verification_code}")
        # Here you would add logic to fill name, password, and the code
        # await self.page.locator("input[name='verificationCode']").fill(verification_code)
        # ...
        await self.page.screenshot(path="registration_final.png")
        print("Final step captured.")
