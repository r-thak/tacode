import asyncio
import os
import logging
import random
from dotenv import load_dotenv
from fastapi.staticfiles import StaticFiles

load_dotenv()
from typing import Optional
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from playwright.async_api import async_playwright
try:
    from playwright_stealth import stealth_async
except ImportError:
    from playwright_stealth import Stealth
    async def stealth_async(page):
        await Stealth().apply_stealth_async(page)

import sys
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from bot import TacoBellBot

# Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Rate Limiter
limiter = Limiter(key_func=get_remote_address)
app = FastAPI()
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS
origins = [
    "http://rthak.com",
    "https://rthak.com",
    "http://www.rthak.com",
    "https://www.rthak.com",
    "https://taco.rthak.com",
    "http://localhost",
    "http://localhost:3000",
    "http://localhost:3333",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class UserDetails(BaseModel):
    first_name: str
    last_name: str = "Taco"

class GetCodeRequest(BaseModel):
    email: str

from fastapi.responses import StreamingResponse
import json

async def run_bot_signup_stream(user_details: UserDetails):
    browser = None
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=[
                    '--disable-blink-features=AutomationControlled',
                    '--no-sandbox',
                    '--disable-setuid-sandbox',
                    '--disable-http2'
                ]
            )
            
            context = await browser.new_context(
                viewport={"width": 1920, "height": 1080},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
                locale='en-US',
                timezone_id='America/New_York',
                permissions=['geolocation'],
                geolocation={'latitude': 40.7128, 'longitude': -74.0060},
                ignore_https_errors=True
            )
            
            await context.route("**/*{fullstory,google-analytics,doubleclick,hotjar,segment}*", lambda route: route.abort())
            current_dir = os.path.dirname(os.path.abspath(__file__))
            db_path = os.path.join(current_dir, "..", "accounts.sqlite")
            
            bot = TacoBellBot(context, db_path=db_path)
            await bot.start()
            
            await bot.page.set_viewport_size({"width": 1920, "height": 1080})
            
            await stealth_async(bot.page)
            
            logger.info("Starting registration via API...")
            email = await bot.get_email()
            
            yield json.dumps({"status": "email_generated", "email": email}) + "\n"
            
            await bot.navigate_to_signup()
            await bot.fill_registration_form({
                "email": email
            })
            
            logger.info("Checking inbox for verification email...")
            code = await bot.wait_for_verification_code()
            logger.info(f"VERIFICATION CODE: {code}")
            
            await bot.complete_signup({
                "first_name": user_details.first_name,
                "last_name": user_details.last_name,
            }, code)
            
            logger.info("Yielding success...")
            yield json.dumps({"status": "success", "email": email, "code": code, "message": "Account created successfully"}) + "\n"

    except Exception as e:
        logger.error(f"Bot execution failed: {e}")
        yield json.dumps({"status": "error", "detail": str(e)}) + "\n"
    
    finally:
        if browser:
            try:
                await browser.close()
            except:
                pass

@app.post("/dispense")
@limiter.limit("5/15 minute")
async def dispense_account(request: Request, user_details: UserDetails):
    return StreamingResponse(run_bot_signup_stream(user_details), media_type="application/x-ndjson")

@app.post("/get_code")
@limiter.limit("5/15 minute")
async def get_login_code(request: Request, body: GetCodeRequest):
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                '--disable-blink-features=AutomationControlled',
                '--no-sandbox',
                '--disable-setuid-sandbox',
                '--disable-http2'
            ]
        )
        try:
            context = await browser.new_context()
            current_dir = os.path.dirname(os.path.abspath(__file__))
            db_path = os.path.join(current_dir, "..", "accounts.sqlite")
            bot = TacoBellBot(context, db_path=db_path)
            
            logger.info(f"Retrieving code for {body.email}...")
            code = await bot.get_code_for_existing_account(body.email)
            return {"status": "success", "code": code}
            
        except Exception as e:
            logger.error(f"Error getting code: {e}")
            raise HTTPException(status_code=500, detail=str(e))
        finally:
            await browser.close()
current_dir = os.path.dirname(os.path.abspath(__file__))
static_dir = os.path.join(current_dir, "..", "static")

if os.path.exists(static_dir):
    app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")
else:
    logger.error(f"Static directory not found at {static_dir}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
