"""Bluetooth control of the xBloom over a connection held while it's in use.

Finding the machine takes 5-30 s (more on a weak signal or right after a disconnect),
so connecting per operation made brews slow and flaky. Instead the server holds the
link while someone is using it: any status check or brew connects and keeps it, and it
is released after XBLOOM_IDLE_MINUTES without activity (default 10). Holding it all day
keeps the machine in connected mode (and it beeps). XBLOOM_WARM_HOURS="6-10" also
holds it during those hours so morning brews start instantly.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from datetime import datetime
from collections.abc import Callable
from dataclasses import dataclass, field

from bleak import BleakScanner
from xbloom_ble import Recipe
from xbloom_ble import client as xbc
from xbloom_ble.client import XBloomClient, XBloomError
from xbloom_ble.protocol import build_commit, build_status_query
from xbloom_ble.telemetry import StatusEvent

log = logging.getLogger(__name__)

# The longest brew we wait for before giving up on telemetry (the brew itself keeps going).
BREW_WATCH_S = 420.0
# Scan and connect are separate steps that rely on bleak's own timeouts: cancelling
# bleak mid-connect leaves it in a broken state.
SCAN_TIMEOUT_S = 45.0
CONNECT_ATTEMPTS = 3
# Last-resort cap on a whole connect sequence (e.g. macOS Bluetooth permission missing).
CONNECT_CAP_S = CONNECT_ATTEMPTS * (SCAN_TIMEOUT_S + 20) + 10
# Background reconnect: wait this long between failed rounds, backing off to the max.
RECONNECT_MIN_S, RECONNECT_MAX_S = 10.0, 120.0
LOAD_TIMEOUT_S = 45.0
# How long to watch for the machine's first reaction to commit.
COMMIT_WATCH_S = 15.0
# The scale streams readings about once a second while connected. This long without
# any frame means the link has died (weak signal); the brew carries on regardless.
SILENCE_S = 45.0
LOST_CONTACT = ("lost contact with the machine during the brew (weak Bluetooth signal). "
                "The machine finishes the brew on its own: check the cup. Don't cancel.")
SEARCHING = "searching for the machine (a cold start can take up to a minute)"


def _idle_s() -> float:
    return float(os.environ.get("XBLOOM_IDLE_MINUTES") or 10) * 60


def _in_warm_hours(now: datetime | None = None) -> bool:
    """True inside XBLOOM_WARM_HOURS, e.g. "6-10" (6:00-9:59) or "22-2" (wraps midnight)."""
    spec = os.environ.get("XBLOOM_WARM_HOURS", "").strip()
    if not spec:
        return False
    try:
        start, end = (int(x) for x in spec.split("-"))
    except ValueError:
        log.warning("ignoring XBLOOM_WARM_HOURS=%r (expected e.g. 6-10)", spec)
        return False
    hour = (now or datetime.now()).hour
    return start <= hour < end if start <= end else (hour >= start or hour < end)


@dataclass
class BrewState:
    recipe_name: str
    dose_g: float
    total_ml: int
    started_at: float = field(default_factory=time.time)
    phase: str = "connecting"
    machine_state: str | None = None
    water_g: float | None = None
    coffee_g: float | None = None
    error: str | None = None
    done: bool = False

    def as_dict(self) -> dict:
        return {
            "recipe": self.recipe_name,
            "dose_g": self.dose_g,
            "phase": self.phase,
            "machine_state": self.machine_state,
            "water_poured_g": self.water_g,
            "coffee_in_cup_g": self.coffee_g,
            "target_water_ml": self.total_ml,
            "elapsed_s": round(time.time() - self.started_at),
            "error": self.error,
            "done": self.done,
        }


async def commit_only(client: XBloomClient, on_event: Callable[[StatusEvent], None]) -> StatusEvent | None:
    """Start the armed brew with commit (0x42) alone.

    xbloom-ble's start() sends a 0x46 "nudge" if it sees no reaction within 8 s. On
    firmware V12.0D.500 the machine always proceeds by itself after commit, but grinds
    silently for ~20 s first, and a 0x46 arriving then ABORTS the brew (seen on
    2026-10-11: stopped mid-grind). So never nudge; just report what the machine does.
    Uses the library's internals, which is why xbloom-ble is pinned to one commit.
    """
    acted = {xbc.STATE_STARTING, xbc.STATE_NO_WATER, xbc.STATE_NO_BEANS} | xbc.BREWING_STATES
    await client._start_notify()  # noqa: SLF001
    try:
        client.reset_water_window()
        await client._write_cmd(build_commit(), "0x42 commit")  # noqa: SLF001
        return await client._drain_for_any(acted, COMMIT_WATCH_S, on_event)  # noqa: SLF001
    finally:
        await client._stop_notify()  # noqa: SLF001


def _friendly(exc: BaseException) -> str:
    text = str(exc)
    if "not found" in text.lower() or isinstance(exc, TimeoutError) or "discovery" in text.lower():
        return ("Couldn't reach the xBloom over Bluetooth. Check it is switched on, and that "
                "no phone app is connected to it (the machine allows only one connection; "
                "turn off Bluetooth for the xBloom app in the phone's settings).")
    return text


class Machine:
    def __init__(self, address: str):
        self.address = address
        self._lock = asyncio.Lock()          # one Bluetooth operation at a time
        self._client: XBloomClient | None = None
        self._keeper: asyncio.Task | None = None
        self.current: BrewState | None = None
        self._task: asyncio.Task | None = None
        self._last_activity = 0.0  # nothing requested yet: don't connect at startup

    def touch(self) -> None:
        """Mark activity: keeps (or starts) the connection for the idle window."""
        self._last_activity = time.time()

    def wanted(self) -> bool:
        return (self.busy or time.time() - self._last_activity < _idle_s()
                or _in_warm_hours())

    # --- connection ------------------------------------------------------------------

    @property
    def connected(self) -> bool:
        return self._client is not None and self._client.is_connected

    @property
    def busy(self) -> bool:
        return self._task is not None and not self._task.done()

    def start(self) -> None:
        """Start the connection manager (call once the event loop is running)."""
        if self.address and (self._keeper is None or self._keeper.done()):
            self._keeper = asyncio.create_task(self._keep_connected())

    async def _keep_connected(self) -> None:
        delay = RECONNECT_MIN_S
        while True:
            if not self.wanted():
                if self._client is not None and not self._lock.locked():
                    log.info("idle: releasing the machine")
                    async with self._lock:
                        await self._drop()
                await asyncio.sleep(5.0)
                continue
            if not self.connected and not self._lock.locked():
                async with self._lock:
                    try:
                        await self._ensure_client()
                        delay = RECONNECT_MIN_S
                    except Exception as exc:  # noqa: BLE001
                        log.info("background connect failed (%r); retrying in %.0fs", exc, delay)
                        await asyncio.sleep(delay)
                        delay = min(delay * 2, RECONNECT_MAX_S)
                        continue
            await asyncio.sleep(5.0)

    async def _ensure_client(self, on_phase: Callable[[str], None] = lambda _: None) -> XBloomClient:
        """Return the held connection, connecting first if needed. Call under self._lock."""
        if self.connected:
            return self._client  # type: ignore[return-value]
        await self._drop()

        async def attempts() -> XBloomClient:
            last: BaseException = TimeoutError("machine not found")
            for attempt in range(1, CONNECT_ATTEMPTS + 1):
                on_phase(SEARCHING)
                device = await BleakScanner.find_device_by_address(self.address, timeout=SCAN_TIMEOUT_S)
                if device is None:
                    log.info("scan %d/%d: machine not found", attempt, CONNECT_ATTEMPTS)
                    last = TimeoutError("machine not found")
                    continue
                on_phase("connecting")
                client = XBloomClient(device)  # type: ignore[arg-type]  # bleak accepts a BLEDevice
                try:
                    await client.connect()
                    await client.open_session(settle=1.0)  # hold the link, keep status flowing
                    return client
                except Exception as exc:  # noqa: BLE001
                    log.info("connect %d/%d failed: %r", attempt, CONNECT_ATTEMPTS, exc)
                    last = exc
                    await _quietly(client.disconnect())
                    await asyncio.sleep(2.0)
            raise last

        self._client = await asyncio.wait_for(attempts(), CONNECT_CAP_S)
        log.info("holding connection to the machine")
        return self._client

    async def _drop(self) -> None:
        if self._client is not None:
            await _quietly(self._client.disconnect())
            self._client = None

    # --- operations ------------------------------------------------------------------

    async def status(self) -> dict:
        """Report what the machine is doing, from the held connection."""
        self.touch()
        if self.busy:
            return {"reachable": True, "state": "brewing", "brew": self.current.as_dict()}  # type: ignore[union-attr]
        async with self._lock:
            try:
                client = await self._ensure_client()
                # Ask explicitly: an idle machine may not have sent a state yet.
                await client._write_cmd(build_status_query(), "0x56 status query")  # noqa: SLF001
                await asyncio.sleep(1.5)
                last = client._last_status  # noqa: SLF001 - library exposes no getter
                return {"reachable": True,
                        "state": last.state_name if last else "unknown",
                        "mode": client.observed_mode()}
            except Exception as exc:  # noqa: BLE001
                await self._drop()
                return {"reachable": False, "error": _friendly(exc)}

    def start_brew(self, recipe: Recipe, on_finish: Callable[[BrewState], None]) -> BrewState:
        if self.busy:
            raise XBloomError("A brew is already running.")
        recipe.validate()
        self.touch()
        self.current = BrewState(recipe.name, recipe.dose_g, recipe.total_water_ml)
        self._task = asyncio.create_task(self._run(recipe, self.current, on_finish))
        return self.current

    async def cancel(self) -> str:
        self.touch()
        try:
            if self.busy and self.connected:
                # The brew task holds the lock while it streams; send on the shared link.
                await self._client.cancel_brew()  # type: ignore[union-attr]
                await asyncio.sleep(1.0)
                self._task.cancel()  # type: ignore[union-attr]
            else:
                async with self._lock:
                    client = await self._ensure_client()
                    await client.cancel_brew()
                    await asyncio.sleep(1.0)
        except Exception as exc:  # noqa: BLE001
            return f"Cancel failed: {_friendly(exc)}"
        if self.current and not self.current.done:
            self.current.phase = "cancelled"
            self.current.done = True
        return "Cancel sent to the machine."

    async def _run(self, recipe: Recipe, st: BrewState,
                   on_finish: Callable[[BrewState], None]) -> None:
        last_frame = [time.time()]

        def record(ev: StatusEvent) -> None:
            last_frame[0] = time.time()
            if ev.is_heartbeat and ev.water_g is None and ev.coffee_g is None:
                return
            if ev.state_name not in ("scale",):
                st.machine_state = ev.state_name
            if ev.water_g is not None:
                st.water_g = ev.water_g
            if ev.coffee_g is not None:
                st.coffee_g = ev.coffee_g

        def set_phase(phase: str) -> None:
            st.phase = phase

        try:
            async with self._lock:
                for attempt in (1, 2):
                    client = await self._ensure_client(set_phase)
                    st.phase = "loading recipe"
                    try:
                        await asyncio.wait_for(client.load_recipe(recipe), LOAD_TIMEOUT_S)
                        break
                    except (XBloomError, TimeoutError) as exc:
                        if attempt == 2:
                            raise
                        # The machine stays silent if it was already holding a loaded
                        # recipe (or the link went bad). Clear it, reconnect, retry once.
                        log.info("load failed (%r); clearing machine and retrying", exc)
                        st.phase = "clearing previous recipe"
                        await _quietly(client.cancel_brew())
                        await asyncio.sleep(3.0)
                        await self._drop()

                st.phase = "starting (grinds silently for ~20 s, then pours)"
                ev = await commit_only(client, record)
                if ev is not None:
                    record(ev)
                if ev is not None and ev.state_name in ("no_water", "no_beans"):
                    what = "no water in the tank" if ev.state_name == "no_water" else "no beans in the grinder"
                    st.error = f"The machine refused to brew: {what}."
                    st.phase = "refused"
                    await client.cancel_brew()
                    return

                st.phase = "brewing"
                last_frame[0] = time.time()
                watch = asyncio.create_task(client.stream_telemetry(record, duration=BREW_WATCH_S))
                while not watch.done():
                    await asyncio.wait({watch}, timeout=2.0)
                    silent = time.time() - last_frame[0]
                    if not watch.done() and (not client.is_connected or silent > SILENCE_S):
                        log.info("lost contact mid-brew (connected=%s, silent %.0fs)",
                                 client.is_connected, silent)
                        watch.cancel()
                        await self._drop()
                        st.phase = LOST_CONTACT
                        return
                watch.result()
                st.phase = "finished"
        except asyncio.CancelledError:
            st.phase = "cancelled"
            raise
        except Exception as exc:  # noqa: BLE001
            log.exception("brew failed")
            await self._drop()
            st.error = _friendly(exc)
            st.phase = "failed"
        finally:
            self.touch()  # keep the link a while for status checks and the next cup
            st.done = True
            try:
                on_finish(st)
            except Exception:  # noqa: BLE001
                log.exception("on_finish failed")


async def _quietly(coro) -> None:
    try:
        await coro
    except Exception:  # noqa: BLE001
        pass
