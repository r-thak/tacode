# Taco Bell Registration Bot
An automated account registration and management tool for Taco Bell.

> **This branch's premise didn't survive contact with the real app.** The
> idea was: the `main` branch (Playwright/browser-based, archived at
> [`archive/playwright-web`](../../tree/archive/playwright-web)) died to Taco
> Bell's web bot-detection and mail-domain blocklist, so drive the real
> Android app in an emulator instead. I got the real app running against a
> real APK end to end (see below) and submitted an actual sign-up. Result:
> the app ships **more** anti-bot instrumentation than the website, not
> less. At the moment the sign-up request goes out, the app's `BMP:*`
> components (Akamai Bot Manager's behavioral-biometrics SDK) collect
> motion/gyroscope/touch/keystroke-timing sensor data and ship it alongside
> the request:
> ```
> BMP:CYFManager: Building sensor data: Thread[OkHttp https://www.tacobell.com/...]
> BMP:MotionManager: Motion Event Count: 128/128
> BMP:TouchManager: Touch Event Count: 18 (move: 0, updown: 18)
> BMP:TextChangeManager: mEvent Count: 9, Key String ...  (per-keystroke timing)
> ```
> ...followed immediately by a generic "Uh-oh! We're experiencing a system
> error" dialog. That's strong circumstantial evidence of a
> behavioral-biometrics soft-block (not a decrypted server verdict, but the
> timing is the textbook pattern) -- a headless AVD doesn't have real motion
> sensors or human touch/typing cadence to feed it. See `src/bot.py`'s module
> docstring for the full detail, including a second, later finding: the
> sign-up button itself wouldn't reliably enable under Appium-synthesized
> input across repeated live runs, though a raw `adb shell input tap` did it
> once -- plausibly the same defense one layer earlier.
>
> I'm not attempting to spoof sensor data or otherwise defeat this -- that's
> evasion tooling against a commercial anti-fraud vendor's product, not
> something this repo does. Getting further would need a physical device
> with real sensors and real human input, which is a different project.
> Also unresolved regardless: the original mail-domain blocklist problem is
> transport-agnostic and would likely still apply even if the above weren't
> blocking things.
>
> What's real and worth keeping despite the negative result: a fresh AVD
> boots, the real split-APK install works, a genuine Joda-Time crash on
> first boot is fixed, and the onboarding + sign-up-modal selectors in
> `src/bot.py` are calibrated against the real app (v8.90.2), not guessed.
> Someone would otherwise have to redo all of that just to rediscover the
> same wall.

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
2. **Get the Taco Bell APK.** I couldn't automate this myself (see below) --
   it needs a human:
   - Four APK mirrors (apkmirror, apkpure, apkpure.net, apkmonk) all return
     `403` to scripted requests -- Cloudflare bot detection. Defeating that
     would mean building a stealth-browser CAPTCHA-evasion tool aimed at
     someone else's anti-bot system, which I won't do.
   - The Play Store route needs a Google account signed in interactively --
     I don't have credentials and won't create any.
   - What works: download the `.apkm` bundle manually through a normal
     browser from an APK mirror (solving whatever human-facing checks it
     shows), or extract split APKs off a real device with the app installed
     (`adb shell pm path com.tacobell.ordering` then `adb pull`).
   - An `.apkm` is just a zip of split APKs. Extract the ones matching your
     AVD (Apple Silicon Macs: `arm64_v8a`) into one directory:
     ```bash
     unzip -j com.tacobell.ordering*.apkm \
       base.apk split_config.arm64_v8a.apk split_config.xxhdpi.apk split_config.en.apk \
       -d tacobell_apk/
     ```
     Point `TACOBELL_APK_DIR` in `.env` at that directory --
     `emulator_manager.py` installs it via `adb install-multiple` on every
     boot (Appium's `app` capability can't install split APKs, and the AVD
     is wiped every run so nothing persists between calls anyway).
3. In one terminal:
   ```bash
   appium
   ```
4. In another:
   ```bash
   pip install -r requirements.txt
   playwright install chromium   # only needed for EMAIL_PROVIDER=guerrillamail
   python src/server.py
   ```

Note: a freshly-wiped AVD boots with `persist.sys.timezone=America/Chicago`,
which crashes this app at startup via a Joda-Time "zone id not recognised"
error -- `emulator_manager.py` works around this automatically
(`service call alarm 3 s16 UTC` right after boot; `setprop` alone doesn't
stick, the property is read-only on this image). You shouldn't need to touch
this, but if the app is crash-looping, that's the first thing to check.

### Docker
`docker compose up -d --build` still builds an image, but it only runs the
FastAPI process -- there's no emulator inside it. Not the recommended path
on this branch; see the comment in `docker-compose.yml`.

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
  generation, blocklist-domain rotation, inbox parsing, opening a message,
  and session resume all verified working end to end while writing this).

  Caveats, read before flipping this on for real registrations:
  - guerrillamail's own domains (`sharklasers.com`, `guerrillamail.*`,
    `grr.la`, `pokemail.net`, `spam4.me`, ...) are some of the most widely
    blocklisted disposable-mail domains that exist -- if the mail-domain
    blocklist (see the top of this file) was what actually killed the
    archived branch, this will likely still get blocked. It's a drop-in
    transport swap, not a fix for that problem.
  - Addresses and their mail expire after ~1 hour, so `/get_code` only works
    within that window of the original `/dispense` call.

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
