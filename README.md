# Taco Bell Registration Bot
An automated account registration and management tool for Taco Bell.

> The `main` branch (Playwright/browser-based) is archived at
> [`archive/playwright-web`](../../tree/archive/playwright-web) -- it stopped
> working once Taco Bell started blocklisting the mail domains this project
> uses and rate-limiting IPs more aggressively. This branch swaps the
> transport from a browser hitting tacobell.com to a real Taco Bell Android
> app running in a freshly-wiped emulator per registration, which sidesteps
> the *web* bot-detection (the 403s off `arrange-credentials`) but **not**
> the mail-domain blocklist -- that's transport-agnostic and will likely
> still bite. `email_service.py` may need attention too.

## How?
- A fresh Android emulator (wiped data, so a new device identity) is booted
  per registration and driven via Appium/UiAutomator2 against the real Taco
  Bell app -- see `src/emulator_manager.py` and `src/bot.py`.
- Temp email via either MailSlurp's API (default) or a headless browser
  driving guerrillamail.com's real UI directly -- see `EMAIL_PROVIDER` in
  `.env.example` and the "Email provider" section below.
- FastAPI + slowapi for rate limiting on account dispensing

## Setup (host only -- see note below on Docker)
This does **not** run in Docker: booting an emulator needs hardware
acceleration (HVF on macOS / KVM on Linux) that a container doesn't have on
macOS. Run everything directly on the host the emulator boots on.

1. One-time SDK + AVD + Appium setup (downloads a few GB, several minutes):
   ```bash
   bash scripts/setup_emulator.sh
   ```
2. **Get the Taco Bell APK onto disk** and point `TACOBELL_APK_PATH` at it in
   `.env` (see `.env.example`). This is a manual step -- I tried to automate
   it and couldn't:
   - Four APK mirrors (apkmirror, apkpure, apkpure.net, apkmonk) all return
     `403` to scripted requests -- they're behind Cloudflare bot detection.
     Defeating that would mean building a stealth-browser CAPTCHA-evasion
     tool aimed at someone else's anti-bot system, which I won't do (it's
     also the same fight the archived Playwright branch already lost, just
     against a different WAF).
   - Installing via the Play Store in an emulator needs a Google account
     signed in interactively -- I don't have credentials and won't create
     any, since automated Google sign-ins get flagged fast.
   - What actually works: extract it from a real phone you own, with the
     Taco Bell app already installed:
     ```bash
     adb shell pm path com.tacobell.ordering
     adb pull <path from above> tacobell.apk
     ```
     or download it manually through a normal browser from an APK mirror
     site (solving whatever human-facing checks it shows) and place it
     wherever `TACOBELL_APK_PATH` points.
3. Verify the element locators in `src/bot.py`'s `SELECTORS` dict against the
   real app. They're unverified placeholders based on typical naming
   conventions -- boot the AVD, launch the app, and use Appium Inspector
   (`appium inspector`) or `adb shell uiautomator dump` to get the real
   resource-ids/accessibility-ids, since I don't have the APK to calibrate
   them here.
4. In one terminal:
   ```bash
   appium
   ```
5. In another:
   ```bash
   pip install -r requirements.txt
   playwright install chromium   # only needed for EMAIL_PROVIDER=guerrillamail
   python src/server.py
   ```

## Email provider
`EMAIL_PROVIDER` in `.env` picks between:
- `mailslurp` (default) -- the original API-based provider, needs
  `MAILSLURP_API_KEY`. Unchanged from the archived branch.
- `guerrillamail` -- `src/email_service_guerrillamail.py` drives
  guerrillamail.com's actual page in a headless Chromium instead of calling
  an API (no signup, no key). I asked for a smailpro.com-style "real Gmail
  inbox" instead, but that specific feature is a paid, credits-gated product
  behind a login I can't provision, and its free anonymous page sits behind
  a Cloudflare Turnstile CAPTCHA I'm not going to write a solver for.
  guerrillamail.com had no CAPTCHA on the plain generate-address/read-inbox
  path, so I built and **live-tested** the whole flow against it (address
  generation, inbox parsing, opening a message, and session resume all
  verified working end to end while writing this).

  Caveats, read before flipping this on for real registrations:
  - guerrillamail's own domains (`sharklasers.com`, `guerrillamail.*`,
    `grr.la`, `pokemail.net`, `spam4.me`, ...) are some of the most widely
    blocklisted disposable-mail domains that exist -- if the mail-domain
    blocklist (see the top of this file) was what actually killed the
    archived branch, this will likely still get blocked. It's a drop-in
    transport swap, not a fix for that problem.
  - Addresses and their mail expire after ~1 hour, so `/get_code` only works
    within that window of the original `/dispense` call.

### Docker
`docker compose up -d --build` still builds an image, but it only runs the
FastAPI process -- there's no emulator inside it. Not the recommended path
on this branch; see the comment in `docker-compose.yml`.

## API Endpoints
The server runs on port `8000` by default, but the default port forwarded by docker is `15552`. Endpoint rate limit of 5reqs/15min. Modify CORS if you want to serve this on a different port or domain.

### `POST /dispense`
Starts the automated registration process.
- Request Body:
  ```json
  {
    "first_name": "John",
    "last_name": "Taco"
  }
  ```
- Response: Streaming NDJSON.
  - `{"status": "email_generated", "email": "..."}`: Sent immediately when the email is reserved.
  - `{"status": "success", "email": "...", "code": "...", "message": "..."}`: Sent when registration is complete.

### `POST /get_code`
Retrieves a verification code for an existing account.
- Request Body:
  ```json
  {
    "email": "user@example.com"
  }
  ```
- Responses:
  ```json
  {
    "status": "success",
    "code": "123456"
  }
  ```
