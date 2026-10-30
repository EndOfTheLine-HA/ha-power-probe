"""Isolated Home Assistant instance with a fake house on the meter."""

from __future__ import annotations

import asyncio
import shutil
from collections.abc import Callable
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant import loader
from homeassistant.config_entries import ConfigEntries
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from custom_components.power_probe.const import DOMAIN
from custom_components.power_probe.measurement import Driver

METER = "sensor.house_power"
DEVICE = "switch.heater"


@pytest.fixture
async def hass(tmp_path):
    source = Path(__file__).parents[1] / "custom_components" / DOMAIN
    shutil.copytree(
        source,
        tmp_path / "custom_components" / DOMAIN,
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    instance = HomeAssistant(str(tmp_path))
    instance.config_entries = ConfigEntries(instance, {})
    loader.async_setup(instance)
    dr.async_setup(instance)
    await dr.async_load(instance, load_empty=True)
    await er.async_load(instance, load_empty=True)
    # This instance runs no web server or frontend. Marking them set up keeps
    # Home Assistant from starting them as dependencies, and skip_pip keeps it
    # from installing the frontend package they would need.
    instance.config.skip_pip = True
    instance.config.components.update(
        {"http", "websocket_api", "panel_custom", "frontend"}
    )
    yield instance
    await instance.async_stop(force=True)


@pytest.fixture(autouse=True)
def panel():
    """The panel needs a real web server, so its registration is replaced."""
    with (
        patch(
            "custom_components.power_probe.async_register_panel", new=AsyncMock()
        ) as register,
        patch("custom_components.power_probe.async_remove_panel", new=MagicMock()),
    ):
        yield register


class House:
    """A whole-home meter that follows what the fake device is doing.

    Nothing waits in real time: `sleep` advances a clock and republishes the
    meter, so a ten minute run takes milliseconds.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        base: float = 250.0,
        device: float = 60.0,
        unit: str = "W",
    ) -> None:
        self.hass = hass
        self.base = base
        self.device = device
        self.unit = unit
        self.on = False
        self.t = 0.0
        # Extra watts per second of run time, for a house that is changing.
        self.drift_per_s = 0.0
        # Called with the clock on every sleep; lets a test stall the run.
        self.on_sleep: Callable[[float], object] | None = None
        # When False the device ignores commands, like a dead switch.
        self.obeys = True
        self.commands: list[tuple[str, str]] = []

        async def turn_on(call: ServiceCall) -> None:
            await self._command(call, True)

        async def turn_off(call: ServiceCall) -> None:
            await self._command(call, False)

        hass.services.async_register("homeassistant", "turn_on", turn_on)
        hass.services.async_register("homeassistant", "turn_off", turn_off)
        self.publish_device()
        self.publish()

    async def _command(self, call: ServiceCall, on: bool) -> None:
        entity_id = call.data["entity_id"]
        self.commands.append((entity_id, "on" if on else "off"))
        if self.obeys:
            self.on = on
            self.publish_device()
            self.publish()

    def publish_device(self) -> None:
        self.hass.states.async_set(
            DEVICE, "on" if self.on else "off", {"friendly_name": "Heater"}
        )

    def publish(self) -> None:
        watts = self.base + self.drift_per_s * self.t + (self.device if self.on else 0)
        value = watts / 1000 if self.unit == "kW" else watts
        self.hass.states.async_set(
            METER,
            str(round(value, 4)),
            {
                "unit_of_measurement": self.unit,
                "device_class": "power",
                "friendly_name": "House power",
            },
        )

    async def sleep(self, seconds: float) -> None:
        self.t += seconds
        self.publish()
        if self.on_sleep is not None:
            result = self.on_sleep(self.t)
            if asyncio.iscoroutine(result):
                await result
        await asyncio.sleep(0)


@pytest.fixture
def house(hass):
    return House(hass)


class FakeDriver:
    """A Driver for the engine alone: no Home Assistant involved."""

    def __init__(
        self, base: float = 200.0, device: float = 60.0, drift_per_s: float = 0.0
    ):
        self.base = base
        self.device = device
        self.drift_per_s = drift_per_s
        self.on = False
        self.t = 0.0
        self.noise: list[float] = [0.0]
        self.reads = 0
        self.blank = False
        self.switches: list[bool] = []
        self.progress: list = []
        # A meter that only reports every this many seconds, with the noise
        # list indexed by report. Reading it more often repeats the report.
        self.update_every: float | None = None
        # False hides which report a reading came from, like a driver that
        # cannot tell.
        self.ids = True

    async def set_device(self, on: bool) -> None:
        self.on = on
        self.switches.append(on)

    def _report_index(self) -> int:
        return int(self.t // self.update_every)

    def read_power(self) -> float | None:
        if self.blank:
            return None
        self.reads += 1
        if self.update_every:
            index = self._report_index()
            at = index * self.update_every
            noise = self.noise[index % len(self.noise)]
        else:
            at = self.t
            noise = self.noise[self.reads % len(self.noise)]
        return (
            self.base + self.drift_per_s * at + (self.device if self.on else 0)
        ) + noise

    def read_update(self) -> int | None:
        if self.update_every and self.ids:
            return self._report_index()
        return None

    async def sleep(self, seconds: float) -> None:
        self.t += seconds

    def driver(self) -> Driver:
        return Driver(
            set_device=self.set_device,
            read_power=self.read_power,
            sleep=self.sleep,
            on_progress=lambda progress: self.progress.append(progress.as_dict()),
            read_update=self.read_update,
        )
