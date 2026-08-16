# Taco Bell Registration Bot
An automated account registration and management tool for Taco Bell.

> **Status: emulator boot → onboarding → sign-up modal is verified working
> end to end; what the app does with a submitted sign-up is not yet
> settled.** The real app (v8.90.2) ships **more** anti-bot instrumentation
> than the website did: at the moment the sign-up request goes out, the
> app's `BMP:*` components (Akamai Bot Manager's behavioral-biometrics SDK)
> collect motion/gyroscope/touch/keystroke-timing sensor data and ship it
> alongside the request:
> ```
> BMP:CYFManager: Building sensor data: Thread[OkHttp https://www.tacobell.com/...]
> BMP:MotionManager: Motion Event Count: 128/128
> BMP:TouchManager: Touch Event Count: 18 (move: 0, updown: 18)
> BMP:TextChangeManager: mEvent Count: 9, Key String ...  (per-keystroke timing)
> ```
> A headless AVD doesn't have real motion sensors or human touch/typing
> cadence by default, so `src/akamai_evasion.py` feeds it both.
>
> **Countermeasures (implemented in `src/akamai_evasion.py`):**
> - **Sensor injection** — *verified working end-to-end*: continuously feeds
>   realistic accelerometer + gyroscope data into the emulator's virtual
>   sensors via the emulator console telnet protocol (with auth). Simulates
>   gravity (~9.81 m/s²), hand tremor, slow orientation drift, and
>   occasional reorientations. Confirmed via `sensor get` that injected
>   values propagate correctly to Android's sensor framework (magnitude
>   9.806 ≈ gravity, Y axis negative, 8 unique readings over 8s).
> - **Human-like taps** — taps have 50-200ms touch duration + ±3px
>   coordinate jitter (BMP TouchManager detects zero-duration taps).
> - **Typing goes through `mobile: type`, not `send_keys`.** Two other
>   approaches were tried and live-tested broken:
>   - Character-by-character `send_keys` with inter-key delays corrupted the
>     input outright -- the email field is a React Native `TextInput`, and
>     each keystroke's native edit raced the JS bridge's controlled-input
>     round-trip (`onChangeText` -> `setState` -> re-render -> `setText`);
>     the per-char delay let the stale re-render clobber the previous
>     character every time (`william@gmail.com` came out as `m`).
>   - Plain bulk `send_keys` didn't corrupt the text, but it sets the
>     EditText's buffer via the accessibility `ACTION_SET_TEXT` action,
>     which never fires a real `TextWatcher`/`onChangeText` event -- the
>     field showed the correct email, but "SIGN UP NOW" stayed permanently
>     disabled (confirmed via the button's `enabled`/`clickable`
>     accessibility attributes, not just a screenshot). `mobile: type`
>     dispatches real Android `KeyEvent`s instead, which the app's
>     controlled-input state actually sees. Verified live: this is the one
>     strategy (of four tried) that flips the button to enabled, and a real
>     tap with it advances past the modal instead of no-opping. See `_type`
>     in `bot.py`.
>
> What's verified: a fresh AVD boots, the real split-APK install works, a
> genuine Joda-Time crash on first boot is fixed, the onboarding gauntlet
> reaches the real Taco Bell home screen, the sign-up modal accepts a real
> email, and its confirm button enables and actually submits. What's
> **not** settled: one same-session live run submitting a
> `guerrillamail.com` address (a heavily blocklisted domain, see the
> "Email provider" section) hit the app's generic error dialog; a separate
> run with a real-domain address advanced past the modal with the outcome
> unobserved. A mail-domain rejection fits the one observed failure at
> least as well as an Akamai behavioral-biometrics soft-block does --
> telling those apart needs a same-domain-as-a-known-good-address A/B,
> not yet run. Don't read the one error dialog as "BMP won." The
> `smailpro` email provider is broken (see "Email provider" below) -- use
> `guerrillamail` or `mailslurp` instead.

## How?
- A fresh Android emulator (wiped data, so a new device identity) is booted
  per registration and driven via Appium/UiAutomator2 against the real Taco
  Bell app -- see `src/emulator_manager.py` and `src/bot.py`.
- Akamai BMP behavioral-biometrics evasion via `src/akamai_evasion.py`:
  - **Sensor stream**: injects realistic accelerometer + gyroscope data into
    the emulator's virtual sensors (gravity + tremor + drift + reorientation)
    via the emulator console telnet protocol. Starts automatically after boot
    in `emulator_manager.acquire_emulator()`.
  - **Human-like taps**: 50-200ms duration + coordinate jitter, via `bot.py`'s
    `_tap`. Tunable via `AKAMAI_*` env vars (see `.env.example`). Typing goes
    through Appium's `mobile: type` -- see the top of this file for why the
    two `send_keys`-based approaches were tried and reverted.
- Temp email via MailSlurp's API (default), a headless browser driving
  guerrillamail.com's real UI, or a headless browser driving smailpro.com
  (currently broken, see "Email provider" below) -- see `EMAIL_PROVIDER` in
  `.env.example`.
- FastAPI + slowapi for rate limiting on account dispensing

## Setup (host only -- see note below on Docker)
This does **not** run in Docker: booting an emulator needs hardware
acceleration (HVF on macOS / KVM on Linux) that a container doesn't have on
macOS. Run everything directly on the host the emulator boots on.

1. One-time SDK + AVD + Appium setup (downloads a few GB, several minutes):
   ```bash
   bash scripts/setup_emulator.sh
   ```
2. **Get the Taco Bell APK.** This step needs a human, not automation:
   - Four APK mirrors (apkmirror, apkpure, apkpure.net, apkmonk) all return
     `403` to scripted requests -- Cloudflare bot detection.
   - The Play Store route needs a Google account signed in interactively.
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
  an API (no signup, no key). **Live-tested and verified working** end to
  end (address generation, blocklist-domain rotation, inbox parsing,
  opening a message, session resume, and a real sign-up submission through
  the emulator all confirmed working).

  Caveats, read before flipping this on for real registrations:
  - guerrillamail's own domains (`sharklasers.com`, `guerrillamail.*`,
    `grr.la`, `pokemail.net`, `spam4.me`, ...) are some of the most widely
    blocklisted disposable-mail domains that exist -- if the mail-domain
    blocklist (see the top of this file) was what actually killed the
    archived branch, this may still get blocked at the account-verification
    stage even though the app itself accepts the submission.
  - Addresses and their mail expire after ~1 hour, so `/get_code` only works
    within that window of the original `/dispense` call.
- `smailpro` -- **currently broken, do not use.** `src/email_service_smailpro.py`
  drives smailpro.com's page, but the real "Create" flow sits behind a live
  Cloudflare Turnstile challenge that the provider never solves. Live
  testing showed it silently falls through to a fallback regex that scrapes
  any `@gmail.com`/`@outlook.com`-looking string off the page -- including
  `william@gmail.com`, which is just example text in the site's own FAQ
  about Gmail's dot trick, not a generated address. Every "generated"
  address from this provider was that same constant string, meaning every
  registration attempt through it submitted a nonexistent mailbox. Needs
  either a Turnstile solve or a different (non-Cloudflare-gated) acquisition
  path before it's usable; until then, use `guerrillamail` or `mailslurp`.

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
