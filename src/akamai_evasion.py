"""
Akamai Bot Manager (BMP) evasion for Android emulators.

The Taco Bell app ships Akamai's behavioral-biometrics SDK, which collects:
  - MotionManager:    accelerometer + gyroscope events (count, values, timing)
  - TouchManager:     touch events (move vs updown count, pressure, duration)
  - TextChangeManager: per-keystroke timing (interval between each key press)

On a headless AVD, these sensors either return zeros or produce no events at all,
and Appium-synthesized taps have zero pressure/duration — the BMP SDK can
trivially distinguish this from a real human holding a phone.

This module provides two countermeasures:

1.  SensorStream — continuously injects realistic accelerometer and gyroscope
    data into the emulator's virtual sensors via the emulator console telnet
    protocol. Spawns a background async task that:
      - simulates gravity (~9.81 m/s²) plus natural hand tremor
      - varies phone tilt slightly over time (nobody holds perfectly still)
      - injects occasional "pick up / set down" reorientation events
    The stream runs for the lifetime of the registration session.

2.  HumanGesture — wraps Appium taps with human-like characteristics:
      - taps have a realistic duration (not instantaneous)
      - tap coordinates have slight random jitter
    (Typing is NOT humanized here -- character-by-character send_keys was
    tried and reverted after it corrupted input on this app's React Native
    TextInput; see the comment on HumanGesture below. bot.py uses plain
    bulk send_keys instead.)
"""

import asyncio
import logging
import math
import os
import random
import time

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tunables — tweak these to match real-device sensor traces if you have them
# ---------------------------------------------------------------------------

SENSOR_UPDATE_INTERVAL = float(os.environ.get("AKAMAI_SENSOR_INTERVAL", "0.2"))
# Gravity on Earth in m/s². When a phone is held upright, gravity pulls along
# the -Y axis in Android's accelerometer coordinate system.
GRAVITY = 9.81

# Hand tremor: random noise added to each axis every update (m/s²).
TREMOR_SIGMA_ACCEL = float(os.environ.get("AKAMAI_TREMOR_ACCEL", "0.15"))
TREMOR_SIGMA_GYRO = float(os.environ.get("AKAMAI_TREMOR_GYRO", "0.05"))

# Natural tilt when holding a phone (radians from vertical, on each axis).
# These define the "resting" orientation the phone drifts toward.
DEFAULT_PITCH = float(os.environ.get("AKAMAI_DEFAULT_PITCH", "0.35"))   # rad, ~20° tilt back
DEFAULT_ROLL = float(os.environ.get("AKAMAI_DEFAULT_ROLL", "0.05"))    # rad, ~3° tilt right

# How fast the simulated tilt drifts (rad/s).
DRIFT_RATE = float(os.environ.get("AKAMAI_DRIFT_RATE", "0.03"))

# How often the simulated user "reorients" the phone (seconds).
REORIENT_INTERVAL_MEAN = float(os.environ.get("AKAMAI_REORIENT_INTERVAL", "15.0"))
REORIENT_DURATION = float(os.environ.get("AKAMAI_REORIENT_DURATION", "1.5"))

# Touch humanization. (No typing-delay constants here -- see the comment in
# HumanGesture below on why char-by-char typing was tried and reverted.)
TAP_DURATION_MS = (50, 200)          # ms, how long the finger stays down
TAP_JITTER_PX = 3                     # px, random offset from target center

# ---------------------------------------------------------------------------
# Sensor data model
# ---------------------------------------------------------------------------


class SensorSimulator:
    """Stateful simulator of a phone being held by a real person.

    Models:
      - gravity on the dominant axis with small tremor
      - slow drift of phone orientation
      - occasional intentional reorientations (pick up, adjust grip, set down)
      - gyroscope reading consistent with the orientation changes
    """

    def __init__(self):
        # Current pitch and roll in radians (deviation from vertical).
        self._pitch = DEFAULT_PITCH
        self._roll = DEFAULT_ROLL

        # Drift delta for this cycle.
        self._pitch_drift = 0.0
        self._roll_drift = 0.0

        # Reorientation state machine.
        self._reorienting = False
        self._reorient_target_pitch = 0.0
        self._reorient_target_roll = 0.0
        self._reorient_start_pitch = 0.0
        self._reorient_start_roll = 0.0
        self._reorient_progress = 0.0  # 0→1 over REORIENT_DURATION
        self._next_reorient_at = time.monotonic() + random.uniform(
            REORIENT_INTERVAL_MEAN * 0.5, REORIENT_INTERVAL_MEAN * 1.5
        )

    def step(self, dt: float) -> tuple[list[float], list[float]]:
        """Advance the simulation by *dt* seconds.

        Returns (accelerometer [x,y,z] m/s², gyroscope [x,y,z] rad/s).
        """
        now = time.monotonic()

        # --- Reorientation logic ---
        if self._reorienting:
            self._reorient_progress += dt / REORIENT_DURATION
            if self._reorient_progress >= 1.0:
                self._pitch = self._reorient_target_pitch
                self._roll = self._reorient_target_roll
                self._reorienting = False
                self._reorient_progress = 0.0
                self._next_reorient_at = now + random.uniform(
                    REORIENT_INTERVAL_MEAN * 0.5, REORIENT_INTERVAL_MEAN * 1.5
                )
            else:
                # Smooth ease-in-out between start and target orientation.
                t = self._reorient_progress
                t_smooth = t * t * (3 - 2 * t)  # smoothstep
                self._pitch = self._reorient_start_pitch + (self._reorient_target_pitch - self._reorient_start_pitch) * t_smooth
                self._roll = self._reorient_start_roll + (self._reorient_target_roll - self._reorient_start_roll) * t_smooth

            # During reorientation, gyroscope reflects the movement.
            gyro_x = (self._reorient_target_pitch - self._reorient_start_pitch) / REORIENT_DURATION
            gyro_y = (self._reorient_target_roll - self._reorient_start_roll) / REORIENT_DURATION
            gyro_z = 0.0
        elif now >= self._next_reorient_at:
            # Start a new reorientation.
            self._reorienting = True
            self._reorient_start_pitch = self._pitch
            self._reorient_start_roll = self._roll
            self._reorient_target_pitch = DEFAULT_PITCH + random.uniform(-0.3, 0.3)
            self._reorient_target_roll = DEFAULT_ROLL + random.uniform(-0.15, 0.15)
            self._reorient_progress = 0.0
            gyro_x = gyro_y = gyro_z = 0.0
        else:
            # Normal drift — random walk of the resting orientation.
            self._pitch_drift += random.uniform(-DRIFT_RATE, DRIFT_RATE) * dt * 0.5
            self._roll_drift += random.uniform(-DRIFT_RATE, DRIFT_RATE) * dt * 0.5
            # Dampen drift so it doesn't wander to extremes.
            self._pitch_drift *= 0.95
            self._roll_drift *= 0.95
            # Pull back toward default resting angle.
            self._pitch += (DEFAULT_PITCH - self._pitch) * 0.1 * dt + self._pitch_drift * dt
            self._roll += (DEFAULT_ROLL - self._roll) * 0.1 * dt + self._roll_drift * dt
            gyro_x = random.gauss(0, TREMOR_SIGMA_GYRO)
            gyro_y = random.gauss(0, TREMOR_SIGMA_GYRO)
            gyro_z = random.gauss(0, TREMOR_SIGMA_GYRO * 0.5)

        # --- Compute accelerometer from tilt angles ---
        # Android accelerometer coordinate system:
        #   +X → right
        #   +Y → up
        #   +Z → out of screen (pointing at user when held in front)
        #
        # When the phone is held upright (pitch=0, roll=0), gravity is purely
        # along -Y: accel_y ≈ -9.81.
        #
        # Pitch = rotation around X axis (phone tilts forward/back).
        # Roll  = rotation around Y axis (phone tilts left/right).
        # We apply roll first, then pitch (the exact order doesn't matter much
        # for small angles, which this is).

        # Gravity vector in device frame:
        gx = GRAVITY * math.sin(self._roll)
        gy = -GRAVITY * math.cos(self._roll) * math.cos(self._pitch)
        gz = GRAVITY * math.cos(self._roll) * math.sin(self._pitch)

        # Add hand tremor.
        ax = gx + random.gauss(0, TREMOR_SIGMA_ACCEL)
        ay = gy + random.gauss(0, TREMOR_SIGMA_ACCEL)
        az = gz + random.gauss(0, TREMOR_SIGMA_ACCEL)

        # Add gyro noise.
        gx = gyro_x + random.gauss(0, TREMOR_SIGMA_GYRO * 0.3)
        gy = gyro_y + random.gauss(0, TREMOR_SIGMA_GYRO * 0.3)
        gz = gyro_z + random.gauss(0, TREMOR_SIGMA_GYRO * 0.3)

        return [ax, ay, az], [gx, gy, gz]


# ---------------------------------------------------------------------------
# Emulator console (telnet) client
# ---------------------------------------------------------------------------


class SensorStream:
    """Background task that continuously feeds sensor data to an emulator.

    Usage as an async context manager:

        async with SensorStream(console_port=5554) as stream:
            # sensors are running in the background
            ...  # do your automation
        # sensors stopped, connection closed

    Or explicitly:

        stream = SensorStream(5554)
        await stream.start()
        ...
        await stream.stop()
    """

    def __init__(self, console_port: int):
        self._port = console_port
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._task: asyncio.Task | None = None
        self._drain_task: asyncio.Task | None = None
        self._running = False
        self._authenticated = False

    def _read_auth_token(self) -> str | None:
        """Read the emulator console auth token from the standard location.

        Modern Android emulators require authentication before accepting any
        console command. The token lives in ~/.emulator_console_auth_token.
        """
        token_path = os.path.expanduser("~/.emulator_console_auth_token")
        try:
            with open(token_path, "r") as f:
                return f.read().strip()
        except (FileNotFoundError, PermissionError):
            return None

    async def start(self):
        """Open the telnet connection, authenticate, and begin streaming."""
        if self._running:
            return

        # The emulator console takes a moment to come up after the process starts.
        # Retry the connection a few times.
        for attempt in range(20):
            try:
                self._reader, self._writer = await asyncio.wait_for(
                    asyncio.open_connection("127.0.0.1", self._port),
                    timeout=2.0,
                )
                break
            except (ConnectionRefusedError, asyncio.TimeoutError, OSError):
                if attempt < 19:
                    await asyncio.sleep(0.5)
                else:
                    raise RuntimeError(
                        f"Could not connect to emulator console on port {self._port} "
                        f"after 20 attempts. Is the emulator running?"
                    )

        # Drain the initial banner the console sends on connect.
        try:
            await asyncio.wait_for(self._reader.read(4096), timeout=2.0)
        except asyncio.TimeoutError:
            pass

        # Authenticate — modern emulators reject all commands without this.
        # The banner says "type 'auth <auth_token>' to authenticate".
        token = self._read_auth_token()
        if token:
            await self._send(f"auth {token}")
            try:
                resp = await asyncio.wait_for(self._reader.read(4096), timeout=2.0)
                resp_text = resp.decode(errors="ignore")
                if "OK" in resp_text:
                    self._authenticated = True
                    logger.info("Emulator console authenticated.")
                else:
                    logger.warning(f"Emulator console auth response: {resp_text.strip()}")
            except asyncio.TimeoutError:
                logger.warning("Emulator console auth timed out — proceeding anyway.")
        else:
            logger.warning(
                "No emulator console auth token found at "
                "~/.emulator_console_auth_token — sensor commands may be rejected."
            )

        # Verify sensor command is available.
        await self._send("sensor status")
        try:
            resp = await asyncio.wait_for(self._reader.read(4096), timeout=2.0)
            resp_text = resp.decode(errors="ignore")
            if "KO" in resp_text or "unknown" in resp_text.lower():
                logger.error(f"Emulator console rejected 'sensor status': {resp_text.strip()}")
                raise RuntimeError(
                    "Emulator console does not support 'sensor' commands. "
                    "Ensure you're running a recent Android emulator with "
                    "virtual sensor support (Goldfish sensors)."
                )
            logger.info(f"Sensor status: {resp_text.strip()[:100]}")
        except asyncio.TimeoutError:
            pass

        self._running = True
        # Background task that continuously reads and discards console
        # responses ("OK\r\n" per command). Without this, the TCP receive
        # buffer fills up after a few seconds of rapid commands and the
        # console silently stops processing new sensor updates.
        self._drain_task = asyncio.create_task(self._response_drain_loop())
        self._task = asyncio.create_task(self._sensor_loop())
        logger.info(f"Sensor stream started on port {self._port}.")

    async def stop(self):
        """Stop the sensor stream and close the console connection."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

        if self._drain_task:
            self._drain_task.cancel()
            try:
                await self._drain_task
            except asyncio.CancelledError:
                pass
            self._drain_task = None

        if self._writer:
            try:
                self._writer.close()
                await self._writer.wait_closed()
            except Exception:
                pass
            self._writer = None
            self._reader = None

        logger.info("Sensor stream stopped.")

    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(self, *_):
        await self.stop()

    async def _send(self, command: str):
        """Send a command to the emulator console."""
        if not self._writer:
            return
        try:
            self._writer.write((command + "\n").encode())
            await self._writer.drain()
        except Exception:
            logger.debug("Lost connection to emulator console.")

    async def _response_drain_loop(self):
        """Continuously read and discard console responses.

        The emulator console sends 'OK\\r\\n' after each command. If we never
        read these, the TCP receive buffer fills up and the console silently
        stops processing new commands — sensor values stop updating even
        though _send() doesn't error. This background task keeps the receive
        buffer empty for the lifetime of the stream.
        """
        while self._running:
            if self._reader:
                try:
                    await self._reader.read(4096)
                except Exception:
                    break
            else:
                break
            await asyncio.sleep(0.01)

    async def _sensor_loop(self):
        """Main loop: compute and inject sensor data at ~5 Hz."""
        sim = SensorSimulator()
        last_t = time.monotonic()

        while self._running:
            now = time.monotonic()
            dt = now - last_t
            last_t = now

            accel, gyro = sim.step(dt)

            # Format: sensor set acceleration x:y:z
            await self._send(
                f"sensor set acceleration "
                f"{accel[0]:.4f}:{accel[1]:.4f}:{accel[2]:.4f}"
            )
            await self._send(
                f"sensor set gyroscope "
                f"{gyro[0]:.4f}:{gyro[1]:.4f}:{gyro[2]:.4f}"
            )

            try:
                await asyncio.sleep(SENSOR_UPDATE_INTERVAL)
            except asyncio.CancelledError:
                break


# ---------------------------------------------------------------------------
# Human-like gesture helpers (intended for use with Appium WebDriver)
# ---------------------------------------------------------------------------


class HumanGesture:
    """Wraps Appium interaction primitives to inject human-like characteristics.

    The BMP SDK's TouchManager tracks:
      - Move vs updown event counts
      - Touch duration
      - Touch pressure (if the device reports it)

    Raw Appium `clickGesture` is instantaneous — zero touch duration, zero
    pressure history. The methods here use `swipe` with matching start/end
    (a "press" of variable duration) and `longClickGesture` to simulate a
    real finger touching the screen.
    """

    @staticmethod
    async def tap(driver, x: int, y: int, duration_ms: int | None = None) -> None:
        """Tap at (x, y) with realistic touch duration.

        A real human tap lasts 50-200ms. An instantaneous gesture has zero
        duration, which the BMP SDK's TouchManager can detect. We use a swipe
        with identical start/end to create a touch of the given duration.
        """
        if duration_ms is None:
            duration_ms = random.randint(*TAP_DURATION_MS)

        # Add slight jitter — real taps aren't pixel-perfect.
        jx = x + random.randint(-TAP_JITTER_PX, TAP_JITTER_PX)
        jy = y + random.randint(-TAP_JITTER_PX, TAP_JITTER_PX)

        # mobile: clickGesture with duration creates a realistic touch event
        # (pressure down → wait → pressure up) rather than an instantaneous tap.
        driver.execute_script(
            "mobile: clickGesture",
            {"x": jx, "y": jy, "duration": duration_ms},
        )

    # No type_text() here. Tried character-by-character send_keys with
    # inter-key delays to defeat BMP's TextChangeManager keystroke-timing
    # capture -- verified broken instead: live-tested against the real
    # sign-up modal (a React Native TextInput), only the *last* character
    # of the string ended up in the field. Each keystroke's native edit
    # races the JS bridge's controlled-input round-trip (onChangeText ->
    # setState -> re-render -> setText); a per-char delay gives the stale
    # re-render time to clobber the previous character before the next one
    # lands. Plain bulk send_keys avoids the race and is what bot.py uses.
