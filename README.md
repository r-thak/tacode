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
- Temp email using Mailslurp API (maybe will make my own temp email service later)
- FastAPI + slowapi for rate limiting on account dispensing

## Setup (host only -- see note below on Docker)
This does **not** run in Docker: booting an emulator needs hardware
acceleration (HVF on macOS / KVM on Linux) that a container doesn't have on
macOS. Run everything directly on the host the emulator boots on.

1. One-time SDK + AVD + Appium setup (downloads a few GB, several minutes):
   ```bash
   bash scripts/setup_emulator.sh
   ```
2. Get the Taco Bell APK onto disk and point `TACOBELL_APK_PATH` at it in
   `.env` (see `.env.example`) -- extract it from a real device:
   ```bash
   adb shell pm path com.tacobell.ordering
   adb pull <path from above> tacobell.apk
   ```
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
   python src/server.py
   ```

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
