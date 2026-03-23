import os
import logging
from playwright.async_api import Page, BrowserContext
import asyncio
import random
from email_service import EmailService
from database import Database

import re

logger = logging.getLogger(__name__)

class TacoBellBot:
    def __init__(self, context: BrowserContext, db_path="accounts.sqlite"):
        self.context = context
        self.page: Page | None = None
        self.email_service = EmailService()
        self.email_address: str | None = None
        self.debug_dir = "debug"
        self.db = Database(db_path)
        os.makedirs(self.debug_dir, exist_ok=True)

    async def get_code_for_existing_account(self, email: str) -> str: # Get code from existing account
        account = self.db.get_account(email)
        if not account or not account.get('email_password'):
            raise Exception(f"No email password found for {email}")
        
        if self.email_service.login(email, account['email_password']):
            code = await self.wait_for_verification_code()
            self.db.mark_account_used(email)
            return code
        else:
            raise Exception(f"Failed to login to email account for {email}")

    async def start(self): # Start new page and wait
        self.page = await self.context.new_page()

        # Inject stealth scripts to bypass navigator checks
        await self.page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
        """)

        await self.page.set_viewport_size({"width": 1280, "height": 720})

    async def get_email(self) -> str: # Get temporary email
        self.email_address = self.email_service.get_email()
        return self.email_address

    async def navigate_to_signup(self): # Navigate to signup page
        if not self.page:
            raise Exception("Page not initialized.")
        
        try:
            # 1. Start with Google to look less like a bot
            logger.info("Miming human entry: visiting Google first...")
            try:
                await self.page.goto("https://www.google.com", timeout=30000, wait_until="domcontentloaded")
                await self.page.wait_for_timeout(random.randint(1000, 3000))
            except Exception as e:
                logger.warning(f"Initial Google visit failed (non-critical): {e}")

            # 2. Go to Taco Bell homepage
            url_home = "https://www.tacobell.com/"
            logger.info(f"Navigating to homepage: {url_home}...")
            try:
                await self.page.goto(url_home, timeout=45000, wait_until="domcontentloaded")
                await self.page.wait_for_timeout(random.randint(2000, 4000))
                # Human-like scroll
                await self.page.mouse.wheel(0, random.randint(300, 700))
                await self.page.wait_for_timeout(random.randint(1000, 2000))
                await self.handle_cookie_banner()
            except Exception as e:
                logger.warning(f"Homepage navigation failed/timed out: {e}")

            # 3. Finally, go to the signup page
            url_signup = "https://www.tacobell.com/register/yum"
            logger.info(f"Navigating to signup directly: {url_signup}...")
            
            # Using longer timeout and load instead of commit for better resilience
            response = await self.page.goto(url_signup, timeout=90000, referer="https://www.tacobell.com/", wait_until="load")
            
            if response and response.status == 403:
                logger.error(f"Signup page blocked (403 Forbidden).")
                
            try:
                # Wait for the email input specifically
                await self.page.wait_for_selector("input[aria-label='Email Address'], input[name='email']", timeout=30000)
                logger.info("Successfully loaded signup page.")
            except Exception:
                logger.warning("Email input not found, checking for blocking screens or errors...")
                # await self.page.screenshot(path=os.path.join(self.debug_dir, "navigation_check.png"))

            await self.page.wait_for_timeout(random.randint(2000, 5000))
        except Exception as e:
            logger.error(f"Navigation failed: {e}")
            try:
                # Ensure debug dir exists before screenshotting
                os.makedirs(self.debug_dir, exist_ok=True)
                # await self.page.screenshot(path=os.path.join(self.debug_dir, f"navigation_failure_{int(asyncio.get_event_loop().time())}.png"), timeout=10000)
            except:
                pass
            raise

    async def handle_cookie_banner(self): # Handle cookie banner
        try:
            agree_button = self.page.locator("button:has-text('AGREE')").first
            if await agree_button.is_visible(timeout=5000):
                await agree_button.click()
                logger.info("Clicked AGREE on cookie banner.")
                await self.page.wait_for_timeout(1000)
        except Exception:
            pass

    async def fill_registration_form(self, user_details: dict): # Fill registration form
        if not self.page:
            raise Exception("Page not initialized.")

        await self.handle_cookie_banner()

        email = user_details.get('email') or self.email_address
        logger.info(f"Inputting email for: {email}")
        
        try:
            email_input = self.page.locator("input[aria-label='Email Address'], input[name='email']").first
            await email_input.wait_for(state="visible", timeout=10000)
            
            import random
            await self.page.wait_for_timeout(random.randint(1000, 3000))
            
            await email_input.click()
            await email_input.fill("")
            await email_input.press_sequentially(email, delay=random.randint(50, 150))
            
            await email_input.press("Tab")
            
            await self.page.wait_for_timeout(random.randint(1000, 2000))
            
            confirm_selectors = [
                "button:has-text('CONFIRM')",
                "button:has-text('Confirm')",
                "button[aria-label='Switch to phone authentication']",
                "form button[type='submit']"
            ]
            
            confirm_button = None
            for selector in confirm_selectors:
                btn = self.page.locator(selector).first
                if await btn.is_visible():
                    confirm_button = btn
                    break
            
            if not confirm_button:
                raise Exception("Could not find the CONFIRM button.")

            logger.info("Clicking CONFIRM button...")
            await confirm_button.hover()
            await self.page.wait_for_timeout(random.randint(500, 1500))
            await confirm_button.click(delay=random.randint(50, 150))
            
            logger.info("Email submitted. Waiting for page transition...")
            
            auth_response = None
            async def handle_response(response):
                nonlocal auth_response
                if "arrange-credentials" in response.url:
                    auth_response = response

            self.page.on("response", handle_response)
            
            try:
                success_selector = "input[aria-label='Enter Code']"
                await self.page.wait_for_selector(success_selector, timeout=30000)
                logger.info("Successfully reached verification step.")
            except Exception:
                logger.warning("Timed out waiting for 'Verify Your Email'. Checking for errors...")
                # await self.page.screenshot(path=os.path.join(self.debug_dir, "transition_timeout.png"))
                
                domain_blocked = False
                
                if auth_response and auth_response.status == 403:
                    logger.error("WAF Block detected: Received 403 Forbidden from arrange-credentials API.")
                    domain_blocked = True

                if await self.page.locator(".styles_has-error__sguR_").first.is_visible(timeout=2000):
                    error_msg = self.page.locator(".styles_has-error__sguR_ >> .styles_error-message__")
                    if await error_msg.is_visible():
                        error_text = await error_msg.inner_text()
                    else:
                        error_text = await self.page.locator(".styles_has-error__sguR_").inner_text()
                    
                    logger.error(f"Form validation error detected: {error_text}")

                if await self.page.locator(".loading-dots, .styles_loading__").first.is_visible(timeout=2000):
                    logger.warning("Still seeing loading indicators. This often means the email domain is blocked or bot detection triggered.")
                    domain_blocked = True
                
                if await confirm_button.is_visible():
                    logger.error("Click didn't transition and button is still visible. Possible silent block.")
                    domain_blocked = True
                
                # if domain_blocked and self.email_address:
                #     domain = self.email_address.split('@')[-1]
                #     logger.info(f"Adding {domain} to blocked_domains.txt")
                #     try:
                #         with open("blocked_domains.txt", "a") as f:
                #             f.write(f"\n{domain}")
                #     except Exception as e:
                #         logger.error(f"Failed to update blocked_domains.txt: {e}")
                
                raise Exception("Registration hung or failed to transition.")
            finally:
                self.page.remove_listener("response", handle_response)

        except Exception as e:
            logger.error(f"Registration failed at email step: {e}")
            # await self.page.screenshot(path=os.path.join(self.debug_dir, "registration_error.png"))
            raise

    async def wait_for_verification_code(self) -> str: # BLOCKING CALL!! Polls for verification code
        loop = asyncio.get_event_loop()
        code = await loop.run_in_executor(None, self.email_service.wait_for_verification_code)
        return code

    async def complete_signup(self, user_details: dict, verification_code: str):
        if not self.page:
            raise Exception("Page not initialized.")
            
        logger.info(f"Entering verification code: {verification_code}")
        
        try: # Enters verification code
            code_input = self.page.locator("input[aria-label='Enter Code']")
            await code_input.wait_for(state="visible", timeout=10000)
            await code_input.click()
            await code_input.press_sequentially(verification_code, delay=random.randint(50, 150))
            
            await self.page.wait_for_timeout(random.randint(1000, 2000))
            
            confirm_btn = self.page.locator("button:has-text('Confirm')").first
            await confirm_btn.click()
            
            # verify and save to db
            logger.info("Verification code submitted. Waiting for next step...")
            await self.page.wait_for_timeout(5000)
            
            # await self.page.screenshot(path=os.path.join(self.debug_dir, "post_code_submission.png"))
            
            try:
                logger.info("Checking for Details form...")
                name_input_selector = "input[name='firstName'], input[aria-label*='First Name'], input[placeholder*='First Name']"
                
                try:
                    await self.page.wait_for_selector(name_input_selector, timeout=10000, state="visible")
                    logger.info("Details form detected. Filling information...")
                    
                    first_name = user_details.get("first_name", "Taco")
                    last_name = user_details.get("last_name", "Lover")
                    
                    # first name
                    first_name_input = self.page.locator(name_input_selector).first
                    await first_name_input.click()
                    await first_name_input.fill(first_name)
                    logger.info("Filled First Name.")
                    
                    # last name
                    last_name_selector = "input[name='lastName'], input[aria-label*='Last Name'], input[placeholder*='Last Name']"
                    last_name_input = self.page.locator(last_name_selector).first
                    if await last_name_input.is_visible(timeout=5000):
                        await last_name_input.click()
                        await last_name_input.fill(last_name)
                        logger.info("Filled Last Name.")

                    # password
                    password_selector = "input[name='password'], input[type='password'], input[aria-label*='Password'], input[placeholder*='Password']"
                    password_input = self.page.locator(password_selector).first
                    if await password_input.is_visible(timeout=2000):
                        await password_input.click()
                        await password_input.fill(user_details.get("password", "TacoBell123!"))
                        logger.info("Filled Password.")

                    # zip code
                    zip_selector = "input[name='zipCode'], input[name='zip'], input[aria-label*='Zip'], input[placeholder*='Zip']"
                    zip_input = self.page.locator(zip_selector).first
                    if await zip_input.is_visible(timeout=2000):
                        await zip_input.click()
                        await zip_input.fill(user_details.get("zip_code", "90210"))
                        logger.info("Filled Zip.")
                    
                    # terms & conditions checkbox
                    checkboxes = self.page.locator("input[type='checkbox']")
                    if await checkboxes.count() > 1:
                        terms_checkbox = checkboxes.nth(1)
                        if await terms_checkbox.is_visible() and not await terms_checkbox.is_checked():
                            await terms_checkbox.check()
                            logger.info("Checked terms checkbox (2nd one).")
                    else:
                        checkbox = checkboxes.first
                        if await checkbox.is_visible() and not await checkbox.is_checked():
                            await checkbox.check()
                            logger.info("Checked value-menu checkbox (only one found).")

                    # submit
                    # Try to find any submit button
                    submit_btn = self.page.locator("button", has_text=re.compile(r"create account|sign up|finish|confirm|let's|save|continue", re.IGNORECASE)).first
                    if not await submit_btn.is_visible():
                        submit_btn = self.page.locator("button[type='submit']").first

                    if await submit_btn.is_visible():
                        logger.info("Found submit button. Clicking...")
                        await submit_btn.wait_for(state="visible", timeout=5000)
                        await submit_btn.click(delay=random.randint(50, 150))
                    else:
                        logger.warning("No submit button found! Check screenshot.")
                        
                        buttons = await self.page.locator("button").all_inner_texts()
                        logger.warning(f"All buttons: {buttons}")
                        page_html = await self.page.content()
                        with open("debug_page.html", "w") as f:
                            f.write(page_html)

                        create_account_btn = self.page.locator("button", has_text=re.compile(r"Create Account|Sign Up|Finish|Create", re.IGNORECASE))
                        if await create_account_btn.first.is_visible():
                            logger.info(f"Clicking '{await create_account_btn.first.inner_text()}' button...")
                            await create_account_btn.first.click()
                        
                    logger.info("Details submitted. Waiting for final transition...")
                    await self.page.wait_for_timeout(5000)
                    
                except Exception as e:
                    logger.info(f"Details form inputs not found or interaction failed: {e}")

            except Exception as e:
                logger.warning(f"Error handling details form wrapper: {e}")
                # await self.page.screenshot(path=os.path.join(self.debug_dir, "details_form_error.png"))

            # await self.page.screenshot(path=os.path.join(self.debug_dir, "registration_final.png"))
            
            email = user_details.get("email") or self.email_address
            
            success = self.db.save_account(
                email=email,
                email_password=self.email_service.session_id,
                first_name=user_details.get("first_name", "Taco"),
                last_name=user_details.get("last_name", "Lover"),
                used=False
            )
            
            if success:
                logger.info(f"Account {email} successfully saved to database.")
            else:
                logger.warning(f"Account {email} could not be saved to database (maybe already exists).")

            print(f"REGISTRATION COMPLETE: {email}")

        except Exception as e:
            logger.error(f"Failed to complete signup: {e}")
            # await self.page.screenshot(path=os.path.join(self.debug_dir, "completion_error.png"))
            raise
