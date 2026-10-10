"""Bluetooth control of the xBloom, one operation at a time.

Each operation connects, does its work, and disconnects, so the phone app can still
use the machine between brews (the machine accepts a single BLE link).
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from bleak import BleakScanner
from xbloom_ble import Recipe
from xbloom_ble.client import XBloomClient, XBloomError
from xbloom_ble.telemetry import StatusEvent

log = logging.getLogger(__name__)

# The longest brew we wait for before giving up on telemetry (the brew itself keeps going).
BREW_WATCH_S = 420.0
# Finding the machine takes 5-30 s (longer from a cold start, or right after another
# connection let go), so scan and connect are separate steps with generous limits, and
# rely on bleak's own timeouts: cancelling bleak mid-connect leaves it in a broken state.
SCAN_TIMEOUT_S = 45.0
CONNECT_ATTEMPTS = 3
# Last-resort cap on a whole connect sequence (e.g. macOS Bluetooth permission missing).
CONNECT_CAP_S = CONNECT_ATTEMPTS * (SCAN_TIMEOUT_S + 20) + 10
LOAD_TIMEOUT_S = 45.0


@dataclass
class BrewState:
    recipe_name: str
    dose_g: float
    total_ml: int
    started_at: float = field(default_factory=time.time)
    phase: str = "searching for the machine (a cold start can take up to a minute)"
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


def _friendly(exc: BaseException) -> str:
    text = str(exc)
    if "not found" in text.lower() or "was not found" in text.lower() or isinstance(exc, TimeoutError):
        return ("Couldn't reach the xBloom over Bluetooth. Check it is switched on, and that "
                "the xBloom phone app isn't connected to it (the machine allows only one "
                "connection; close the app or turn the phone's Bluetooth off).")
    return text


class Machine:
    def __init__(self, address: str):
        self.address = address
        self._lock = asyncio.Lock()
        self.current: BrewState | None = None
        self._task: asyncio.Task | None = None
        self._active: XBloomClient | None = None

    async def _connect(self, on_phase: Callable[[str], None] = lambda _: None) -> XBloomClient:
        """Find the machine, then connect; retry with a fresh scan each time."""
        async def attempts() -> XBloomClient:
            last: BaseException = TimeoutError("machine not found")
            for attempt in range(1, CONNECT_ATTEMPTS + 1):
                on_phase("searching for the machine (a cold start can take up to a minute)")
                device = await BleakScanner.find_device_by_address(self.address, timeout=SCAN_TIMEOUT_S)
                if device is None:
                    log.info("scan %d/%d: machine not found", attempt, CONNECT_ATTEMPTS)
                    last = TimeoutError("machine not found")
                    continue
                on_phase("connecting")
                client = XBloomClient(device)  # type: ignore[arg-type]  # bleak accepts a BLEDevice
                try:
                    await client.connect()
                    return client
                except Exception as exc:  # noqa: BLE001
                    log.info("connect %d/%d failed: %r", attempt, CONNECT_ATTEMPTS, exc)
                    last = exc
                    try:
                        await client.disconnect()
                    except Exception:  # noqa: BLE001
                        pass
                    await asyncio.sleep(2.0)
            raise last

        return await asyncio.wait_for(attempts(), CONNECT_CAP_S)

    @property
    def busy(self) -> bool:
        return self._task is not None and not self._task.done()

    async def status(self) -> dict:
        """Connect briefly and report what the machine says it is doing."""
        if self.busy:
            return {"reachable": True, "state": "brewing", "brew": self.current.as_dict()}  # type: ignore[union-attr]
        async def probe() -> dict:
            async with await self._connect() as client:
                await client.open_session(settle=2.0)
                last = client._last_status  # noqa: SLF001 - library exposes no getter
                return {"reachable": True,
                        "state": last.state_name if last else "unknown",
                        "mode": client.observed_mode()}

        async with self._lock:
            try:
                return await probe()
            except Exception as exc:  # noqa: BLE001
                return {"reachable": False, "error": _friendly(exc)}

    def start_brew(self, recipe: Recipe, on_finish: Callable[[BrewState], None]) -> BrewState:
        if self.busy:
            raise XBloomError("A brew is already running.")
        recipe.validate()
        self.current = BrewState(recipe.name, recipe.dose_g, recipe.total_water_ml)
        self._task = asyncio.create_task(self._run(recipe, self.current, on_finish))
        return self.current

    async def cancel(self) -> str:
        try:
            if self.busy and self._active is not None and self._active.is_connected:
                # Reuse the brew's own link; the machine won't accept a second one.
                await self._active.cancel_brew()
                await asyncio.sleep(1.0)
                self._task.cancel()  # type: ignore[union-attr]
            else:
                async with self._lock:
                    async with await self._connect() as client:
                        await client.cancel_brew()
                        await asyncio.sleep(1.0)
        except Exception as exc:  # noqa: BLE001
            return f"Cancel failed: {_friendly(exc)}"
        if self.current:
            self.current.phase = "cancelled"
            self.current.done = True
        return "Cancel sent to the machine."

    async def _run(self, recipe: Recipe, st: BrewState,
                   on_finish: Callable[[BrewState], None]) -> None:
        def record(ev: StatusEvent) -> None:
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
                    client = await self._connect(set_phase)
                    async with client:
                        self._active = client
                        st.phase = "loading recipe"
                        try:
                            await asyncio.wait_for(client.load_recipe(recipe), LOAD_TIMEOUT_S)
                        except (XBloomError, TimeoutError) as exc:
                            # The machine stays silent if it was already holding a
                            # loaded recipe. Clear it and try once more from idle.
                            if attempt == 1 and (isinstance(exc, TimeoutError) or "timed out" in str(exc)):
                                log.info("load timed out; clearing machine and retrying")
                                st.phase = "clearing previous recipe"
                                await client.cancel_brew()
                                await asyncio.sleep(3.0)
                                continue
                            raise
                        st.phase = "starting"
                        ev = await client.start(on_event=record)
                        record(ev)
                        if ev.state_name in ("no_water", "no_beans"):
                            what = ("no water in the tank" if ev.state_name == "no_water"
                                    else "no beans in the grinder")
                            st.error = f"The machine refused to brew: {what}."
                            st.phase = "refused"
                            await client.cancel_brew()
                            return
                        st.phase = "brewing"
                        await client.stream_telemetry(record, duration=BREW_WATCH_S)
                        st.phase = "finished"
                        return
                raise XBloomError("The machine didn't accept the recipe after clearing it.")
        except asyncio.CancelledError:
            st.phase = "cancelled"
            raise
        except Exception as exc:  # noqa: BLE001
            log.exception("brew failed")
            st.error = _friendly(exc)
            st.phase = "failed"
        finally:
            self._active = None
            st.done = True
            try:
                on_finish(st)
            except Exception:  # noqa: BLE001
                log.exception("on_finish failed")

