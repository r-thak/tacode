
import os
import logging
from playwright.async_api import Page, BrowserContext
import asyncio
import random
from email_service import EmailService
from database import Database

logger = logging.getLogger(__name__)

class TacoBellBot:
    def __init__(self, context: BrowserContext, db_path="accounts.db"):
        self.context = context
        self.page: Page | None = None
        self.email_service = EmailService()
        self.email_address: str | None = None
        self.debug_dir = "debug"
        self.db = Database(db_path)
        os.makedirs(self.debug_dir, exist_ok=True)

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
        logger.info(f"Navigating to {url}...")
        await self.page.goto(url, timeout=60000)
        await self.page.wait_for_load_state("networkidle")

    async def handle_cookie_banner(self):
        """Clicks Agree on the cookie banner if present."""
        try:
            agree_button = self.page.locator("button:has-text('AGREE')").first
            if await agree_button.is_visible(timeout=5000):
                await agree_button.click()
                logger.info("Clicked AGREE on cookie banner.")
                await self.page.wait_for_timeout(1000)
        except Exception:
            pass

    async def fill_registration_form(self, user_details: dict):
        """Fills the initial registration form."""
        if not self.page:
            raise Exception("Page not initialized.")

        await self.handle_cookie_banner()

        email = user_details.get('email') or self.email_address
        logger.info(f"Filling form for: {email}")
        
        try:
            # Enter Email
            email_input = self.page.locator("input[name='email']")
            await email_input.wait_for(state="visible", timeout=10000)
            
            # Add human-like delay
            import random
            await self.page.wait_for_timeout(random.randint(1000, 3000))
            
            await email_input.click()
            await email_input.fill("") # Clear just in case
            await email_input.press_sequentially(email, delay=random.randint(50, 150))
            
            # Wait after typing
            await self.page.wait_for_timeout(random.randint(800, 1500))
            
            # Click Confirm button
            confirm_button = self.page.locator("button:has-text('CONFIRM')").first
            await confirm_button.wait_for(state="visible", timeout=5000)
            await confirm_button.click()
            
            logger.info("Email submitted. Waiting for page transition...")
            
            # Wait for success - usually transitions to "Verify Your Email"
            # Or at least wait for the loading indicator to disappear/new content to appear
            try:
                await self.page.wait_for_selector("text=Verify Your Email", timeout=30000)
                logger.info("Successfully reached verification step.")
            except Exception:
                # If it didn't find the text, maybe it's still loading or showed an error
                logger.warning("Could not confirm 'Verify Your Email' text. Checking for errors...")
                await self.page.screenshot(path=os.path.join(self.debug_dir, "registration_transition_check.png"))
                
                # Check for explicit error messages
                error_msg = await self.page.locator(".error-message, .alert-danger, [role='alert']").first.text_content(timeout=5000)
                if error_msg:
                    logger.error(f"Detected error on page: {error_msg.strip()}")
                else:
                    logger.info("No explicit error message found, but page transition hung.")
                
                # Check if it's still loading
                dots = self.page.locator(".loading-dots, .spinner")
                if await dots.count() > 0:
                    logger.info("Loading indicator is still present.")
                
                await self.page.screenshot(path=os.path.join(self.debug_dir, "registration_step2.png"))
                raise Exception("Registration hung at loading dots.")

        except Exception as e:
            logger.error(f"Registration failed at email step: {e}")
            await self.page.screenshot(path=os.path.join(self.debug_dir, "registration_error.png"))
            raise

    async def wait_for_verification_code(self) -> str:
        """Polls for the verification email and extracts the code."""
        # This uses the EmailService which calls the Mail.tm API
        # We wrap it in to_thread because it's a blocking requests call
        loop = asyncio.get_event_loop()
        code = await loop.run_in_executor(None, self.email_service.wait_for_verification_code)
        return code

    async def complete_signup(self, user_details: dict, verification_code: str):
        """Enters the verification code and other details to finish registration."""
        if not self.page:
            raise Exception("Page not initialized.")
            
        logger.info(f"Entering verification code: {verification_code}")
        
        try:
            # 1. Enter Verification Code
            code_input = self.page.locator("input[aria-label='Enter Code']")
            await code_input.wait_for(state="visible", timeout=10000)
            await code_input.click()
            await code_input.press_sequentially(verification_code, delay=random.randint(50, 150))
            
            await self.page.wait_for_timeout(random.randint(1000, 2000))
            
            confirm_btn = self.page.locator("button:has-text('Confirm')").first
            await confirm_btn.click()
            
            logger.info("Verification code submitted. Waiting for details form...")
            
            # 2. Fill Name and Finish (if asked)
            try:
                first_name_input = self.page.locator("input[aria-label='*First Name']")
                await first_name_input.wait_for(state="visible", timeout=15000)
                
                first_name = user_details.get("first_name", "Taco")
                last_name = user_details.get("last_name", "Lover")
                
                await first_name_input.click()
                await first_name_input.press_sequentially(first_name, delay=random.randint(50, 150))
                
                last_name_input = self.page.locator("input[aria-label='*Last Name']")
                await last_name_input.click()
                await last_name_input.press_sequentially(last_name, delay=random.randint(50, 150))
                
                # Check agreement if present
                checkbox = self.page.locator("input[type='checkbox']").first
                if await checkbox.is_visible():
                    await checkbox.check()
                
                await self.page.wait_for_timeout(1000)
                await confirm_btn.click()
                
                logger.info("Details form submitted.")
            except Exception:
                logger.info("Details form didn't appear or already completed. Checking for success...")

            # 3. Verify Success and Save to DB
            await self.page.wait_for_timeout(5000) # Wait for page to settle
            await self.page.screenshot(path=os.path.join(self.debug_dir, "registration_final.png"))
            
            # Save to Database
            email = user_details.get("email") or self.email_address
            password = user_details.get("password", "PASSWORDLESS")
            
            success = self.db.save_account(
                email=email,
                password=password,
                first_name=user_details.get("first_name", "Taco"),
                last_name=user_details.get("last_name", "Lover")
            )
            
            if success:
                logger.info(f"Account {email} successfully saved to database.")
            else:
                logger.warning(f"Account {email} could not be saved to database (maybe already exists).")

            print(f"REGISTRATION COMPLETE: {email}")

        except Exception as e:
            logger.error(f"Failed to complete signup: {e}")
            await self.page.screenshot(path=os.path.join(self.debug_dir, "completion_error.png"))
            raise
