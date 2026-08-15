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

import sys
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from bot import TacoBellBot
from emulator_manager import acquire_emulator, release_emulator

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
    "http://localhost:15552",
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
    emu = None
    try:
        current_dir = os.path.dirname(os.path.abspath(__file__))
        db_path = os.path.join(current_dir, "..", "accounts.sqlite")

        logger.info("Booting a fresh emulator instance for this registration...")
        emu = await acquire_emulator()

        bot = TacoBellBot(emu.driver, db_path=db_path)
        await bot.start()

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
        if emu:
            try:
                await release_emulator(emu)
            except Exception:
                pass

@app.post("/dispense")
@limiter.limit("5/15 minute")
async def dispense_account(request: Request, user_details: UserDetails):
    return StreamingResponse(run_bot_signup_stream(user_details), media_type="application/x-ndjson")

@app.post("/get_code")
@limiter.limit("5/15 minute")
async def get_login_code(request: Request, body: GetCodeRequest):
    # No emulator/browser needed here: get_code_for_existing_account only
    # talks to the mailbox (email_service.py), so we skip the device entirely.
    current_dir = os.path.dirname(os.path.abspath(__file__))
    db_path = os.path.join(current_dir, "..", "accounts.sqlite")
    bot = TacoBellBot(None, db_path=db_path)

    try:
        logger.info(f"Retrieving code for {body.email}...")
        code = await bot.get_code_for_existing_account(body.email)
        return {"status": "success", "code": code}
    except Exception as e:
        logger.error(f"Error getting code: {e}")
        raise HTTPException(status_code=500, detail=str(e))
current_dir = os.path.dirname(os.path.abspath(__file__))
static_dir = os.path.join(current_dir, "..", "static")

if os.path.exists(static_dir):
    app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")
else:
    logger.error(f"Static directory not found at {static_dir}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
