#!/usr/bin/env bash
# One-time host setup for the emulator branch: installs the Android SDK
# platform-tools/emulator/system-image, creates the AVD the bot reuses for
# every registration, and installs Appium + its UiAutomator2 driver.
#
# Not run automatically -- this downloads a few GB and takes several minutes.
# Review it, then: bash scripts/setup_emulator.sh
set -euo pipefail

ANDROID_HOME="${ANDROID_HOME:-$HOME/Library/Android/sdk}"
AVD_NAME="${TACOBELL_AVD_NAME:-tacobell_base}"
ARCH="$(uname -m)"

if [[ "$ARCH" == "arm64" ]]; then
  SYSTEM_IMAGE="system-images;android-34;google_apis;arm64-v8a"
else
  SYSTEM_IMAGE="system-images;android-34;google_apis;x86_64"
fi

echo "==> Using ANDROID_HOME=$ANDROID_HOME"
mkdir -p "$ANDROID_HOME"

CMDLINE_TOOLS="$ANDROID_HOME/cmdline-tools/latest/bin"
if [[ ! -x "$CMDLINE_TOOLS/sdkmanager" ]]; then
  echo "==> cmdline-tools not found, downloading..."
  TMP=$(mktemp -d)
  if [[ "$(uname)" == "Darwin" ]]; then
    URL="https://dl.google.com/android/repository/commandlinetools-mac-11076708_latest.zip"
  else
    URL="https://dl.google.com/android/repository/commandlinetools-linux-11076708_latest.zip"
  fi
  curl -fsSL "$URL" -o "$TMP/cmdline-tools.zip"
  mkdir -p "$ANDROID_HOME/cmdline-tools"
  unzip -q "$TMP/cmdline-tools.zip" -d "$ANDROID_HOME/cmdline-tools"
  mv "$ANDROID_HOME/cmdline-tools/cmdline-tools" "$ANDROID_HOME/cmdline-tools/latest"
  rm -rf "$TMP"
fi

export PATH="$CMDLINE_TOOLS:$ANDROID_HOME/platform-tools:$ANDROID_HOME/emulator:$PATH"

echo "==> Installing platform-tools, emulator, and $SYSTEM_IMAGE (accepting licenses)..."
yes | sdkmanager --licenses >/dev/null || true
sdkmanager --install "platform-tools" "emulator" "$SYSTEM_IMAGE"

if ! avdmanager list avd | grep -q "Name: $AVD_NAME"; then
  echo "==> Creating AVD '$AVD_NAME'..."
  echo "no" | avdmanager create avd -n "$AVD_NAME" -k "$SYSTEM_IMAGE" -d pixel_6
else
  echo "==> AVD '$AVD_NAME' already exists, skipping."
fi

if ! command -v appium >/dev/null; then
  echo "==> Installing Appium (requires Node/npm)..."
  npm install -g appium
fi

echo "==> Installing Appium UiAutomator2 driver..."
appium driver install uiautomator2 || echo "  (already installed, skipping)"

cat <<EOF

Setup complete.

Still needed before running the bot:
  1. Place the Taco Bell APK somewhere and set TACOBELL_APK_PATH in .env
     (extract it from a real device: 'adb shell pm path com.tacobell.ordering'
     then 'adb pull <path>').
  2. Start the Appium server in one terminal:  appium
  3. Run the bot / server in another:          python src/server.py
  4. Verify the placeholder selectors in src/bot.py's SELECTORS dict against
     the real app using Appium Inspector -- they're unverified guesses.
EOF
