# NOTE: the emulator branch does NOT run the Android emulator in this
# container -- there's no hardware acceleration (HVF/KVM) available to a
# Docker container on macOS, and often not on Linux either without extra
# host config. This image only runs the FastAPI server; it expects an
# Appium server + booted emulator reachable over the network (ANDROID_HOME
# tooling and `adb` must point at a host/VM that actually has them).
#
# The straightforward path is to skip Docker entirely for this branch and
# run `python src/server.py` directly on the host next to the emulator --
# see scripts/setup_emulator.sh and README.md.

FROM python:3.11-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

COPY requirements.txt .

RUN uv pip install --system --no-cache -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["python", "src/server.py"]
