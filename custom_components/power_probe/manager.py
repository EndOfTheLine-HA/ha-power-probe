"""Runs a measurement against real entities and keeps the history."""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Callable, Mapping
from dataclasses import replace
from datetime import datetime
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_UNIT_OF_MEASUREMENT,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    STATE_OFF,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
    UnitOfPower,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util
from homeassistant.util.unit_conversion import PowerConverter

from .const import (
    CONF_CYCLES,
    CONF_INTERVAL,
    CONF_POWER_ENTITY,
    CONF_PROFILE,
    CONF_RESTORE,
    CONF_SETTLE,
    CONF_WINDOW,
    DEFAULT_CUSTOM_TIMING,
    DEFAULT_CYCLES,
    DEFAULT_PROFILE,
    DEFAULT_RESTORE,
    DOMAIN,
    EVENT_FINISHED,
    MAX_HISTORY,
    PROFILE_CUSTOM,
    PROFILE_TIMINGS,
    STATE_CANCELLED,
    STATE_FAILED,
    STATE_FINISHED,
    STATE_MEASURING,
    STATE_TIMEOUT,
    SUPPORTED_DOMAINS,
)
from .export import powercalc_yaml
from .measurement import (
    Driver,
    MeasureSettings,
    Outcome,
    ProbeError,
    Progress,
    Window,
    run_sequence,
    summarize,
)

_LOGGER = logging.getLogger(__name__)

STORAGE_VERSION = 1
POLL_S = 0.5

type ProbeConfigEntry = ConfigEntry[ProbeManager]
type Listener = Callable[[str], None]

# Listener kinds.
KIND_PROGRESS = "progress"
KIND_HISTORY = "history"


class ProbeManager:
    """One config entry's measurements: starts, cancels, remembers."""

    def __init__(self, hass: HomeAssistant, entry: ProbeConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.history: list[dict[str, Any]] = []
        self.progress = Progress()
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, f"{DOMAIN}.history"
        )
        self._listeners: list[Listener] = []
        self._task: asyncio.Task[dict[str, Any]] | None = None
        # Written to disk before the device is first switched and cleared once
        # it is confirmed back where it should be. Still there at startup means
        # a restart or power cut interrupted a run that left the device switched.
        self._active: dict[str, Any] | None = None
        # Replaced in tests so a run does not take real minutes.
        self.sleep = asyncio.sleep

    async def async_load(self) -> None:
        """Read saved results and any run a restart interrupted."""
        stored = await self._store.async_load()
        if stored:
            self.history = list(stored.get("history", []))
            self._active = stored.get("active")

    async def _save(self) -> None:
        await self._store.async_save({"history": self.history, "active": self._active})

    async def async_recover(self) -> None:
        """Put back a device that an interrupted run left switched.

        Called once Home Assistant has started, so the device's own integration
        is up. If the device cannot be confirmed back, the marker stays and the
        next start tries again.
        """
        active = self._active
        if not active or self.busy:
            return
        entity_id = active["entity_id"]
        target_on = bool(active.get("final_on"))
        _LOGGER.warning(
            "A Power Probe run on %s was interrupted by a restart; putting it back %s",
            entity_id,
            "on" if target_on else "off",
        )
        if await self._leave_device(entity_id, target_on):
            self._active = None
            await self._save()
        self._finish(
            Progress(state=STATE_FAILED, entity_id=entity_id, error="interrupted")
        )
        self.hass.bus.async_fire(
            EVENT_FINISHED,
            {"entity_id": entity_id, "success": False, "error": "interrupted"},
        )

    # Listeners ----------------------------------------------------------

    @callback
    def add_listener(self, listener: Listener) -> Callable[[], None]:
        """Call `listener(kind)` on progress and history changes."""
        self._listeners.append(listener)

        @callback
        def remove() -> None:
            if listener in self._listeners:
                self._listeners.remove(listener)

        return remove

    @callback
    def _notify(self, kind: str) -> None:
        for listener in list(self._listeners):
            try:
                listener(kind)
            except Exception:
                _LOGGER.exception("Power Probe listener failed")

    # Settings -----------------------------------------------------------

    @property
    def busy(self) -> bool:
        return self._task is not None and not self._task.done()

    @property
    def last_result(self) -> dict[str, Any] | None:
        return self.history[0] if self.history else None

    @property
    def power_entity(self) -> str | None:
        return self.entry.options.get(CONF_POWER_ENTITY)

    @property
    def default_restore(self) -> bool:
        return bool(self.entry.options.get(CONF_RESTORE, DEFAULT_RESTORE))

    def default_settings(self) -> MeasureSettings:
        """Timing from the entry's options: a preset or the custom numbers."""
        options = self.entry.options
        profile = options.get(CONF_PROFILE, DEFAULT_PROFILE)
        if profile == PROFILE_CUSTOM:
            settle, window, interval = (
                options.get(CONF_SETTLE, DEFAULT_CUSTOM_TIMING[0]),
                options.get(CONF_WINDOW, DEFAULT_CUSTOM_TIMING[1]),
                options.get(CONF_INTERVAL, DEFAULT_CUSTOM_TIMING[2]),
            )
        else:
            settle, window, interval = PROFILE_TIMINGS[profile]
        return MeasureSettings(
            settle_s=float(settle),
            window_s=float(window),
            interval_s=float(interval),
            cycles=int(options.get(CONF_CYCLES, DEFAULT_CYCLES)),
        )

    def info(self) -> dict[str, Any]:
        """Everything the panel needs to draw itself."""
        return {
            "power_entity": self.power_entity,
            "settings": self.default_settings().as_dict(),
            "restore_state": self.default_restore,
            "profiles": {
                name: {"settle_s": s, "window_s": w, "interval_s": i}
                for name, (s, w, i) in PROFILE_TIMINGS.items()
            },
            "supported_domains": list(SUPPORTED_DOMAINS),
            "progress": self.progress.as_dict(),
            "history": self.history,
        }

    # Reading and switching ---------------------------------------------

    def read_update(self, entity_id: str) -> float | None:
        """When the meter last reported, which changes with every new report.

        `last_reported` moves even when the value repeats, so it tells a fresh
        report from the same one read twice.
        """
        state = self.hass.states.get(entity_id)
        return None if state is None else state.last_reported_timestamp

    def read_meter(self, entity_id: str) -> float | None:
        """The meter in watts, or None if it has no usable reading."""
        state = self.hass.states.get(entity_id)
        if state is None or state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE):
            return None
        try:
            value = float(state.state)
        except ValueError:
            return None
        unit = state.attributes.get(ATTR_UNIT_OF_MEASUREMENT)
        if unit == UnitOfPower.WATT:
            return value
        try:
            return PowerConverter.convert(value, unit, UnitOfPower.WATT)
        except HomeAssistantError:
            return None

    def _validate(self, entity_id: str, meter: str | None) -> str:
        """Check a run can start. Returns the meter entity to use."""
        if not meter:
            raise ProbeError("no_meter")
        domain = entity_id.partition(".")[0]
        if domain not in SUPPORTED_DOMAINS:
            raise ProbeError("device_not_supported", domain=domain)
        device = self.hass.states.get(entity_id)
        if device is None or device.state == STATE_UNAVAILABLE:
            raise ProbeError("device_unavailable", entity_id=entity_id)
        meter_state = self.hass.states.get(meter)
        if meter_state is None:
            raise ProbeError("meter_unavailable", entity_id=meter)
        unit = meter_state.attributes.get(ATTR_UNIT_OF_MEASUREMENT)
        if unit not in PowerConverter.VALID_UNITS:
            raise ProbeError("meter_not_power", entity_id=meter, unit=str(unit))
        if self.read_meter(meter) is None:
            raise ProbeError("meter_unavailable", entity_id=meter)
        return meter

    async def _set_device(self, entity_id: str, on: bool) -> None:
        """Switch the device and wait until it reports the new state."""
        await self.hass.services.async_call(
            "homeassistant",
            SERVICE_TURN_ON if on else SERVICE_TURN_OFF,
            {"entity_id": entity_id},
            blocking=True,
        )
        waited = 0.0
        while True:
            state = self.hass.states.get(entity_id)
            if state is not None and _state_matches(state.state, on):
                return
            if waited >= STATE_TIMEOUT:
                raise ProbeError(
                    "device_did_not_change",
                    entity_id=entity_id,
                    target="on" if on else "off",
                )
            await self.sleep(POLL_S)
            waited += POLL_S

    def _is_on(self, entity_id: str) -> bool:
        state = self.hass.states.get(entity_id)
        return state is not None and _state_matches(state.state, True)

    # Running ------------------------------------------------------------

    @callback
    def async_start(
        self, entity_id: str, options: Mapping[str, Any] | None = None
    ) -> asyncio.Task[dict[str, Any]]:
        """Start a run in the background. `options` overrides the defaults."""
        options = options or {}
        try:
            if self.busy:
                raise ProbeError("busy")
            meter = self._validate(
                entity_id, options.get(CONF_POWER_ENTITY) or self.power_entity
            )
            settings = self._settings_with(options)
        except ProbeError as err:
            raise _validation_error(err) from err
        restore = bool(options.get(CONF_RESTORE, self.default_restore))

        self.progress = Progress(state=STATE_MEASURING, entity_id=entity_id)
        self._task = self.entry.async_create_background_task(
            self.hass,
            self._run(entity_id, meter, settings, restore),
            name=f"{DOMAIN} measure {entity_id}",
        )
        self._notify(KIND_PROGRESS)
        return self._task

    def _settings_with(self, options: Mapping[str, Any]) -> MeasureSettings:
        defaults = self.default_settings()
        settings = replace(
            defaults,
            settle_s=float(options.get(CONF_SETTLE, defaults.settle_s)),
            window_s=float(options.get(CONF_WINDOW, defaults.window_s)),
            interval_s=float(options.get(CONF_INTERVAL, defaults.interval_s)),
            cycles=int(options.get(CONF_CYCLES, defaults.cycles)),
        )
        if settings.interval_s > settings.window_s:
            raise ProbeError("interval_longer_than_window")
        return settings

    async def async_cancel(self) -> bool:
        """Stop a running measurement. True if one was running."""
        task = self._task
        if task is None or task.done():
            return False
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        return True

    async def _run(
        self,
        entity_id: str,
        meter: str,
        settings: MeasureSettings,
        restore: bool,
    ) -> dict[str, Any]:
        """The whole run: sequence, put the device back, record, announce."""
        started = dt_util.utcnow()
        was_on = self._is_on(entity_id)
        # Saved before the device is first switched, so a restart mid-run can
        # still put it back.
        self._active = {
            "entity_id": entity_id,
            "final_on": was_on and restore,
            "started_at": started.isoformat(),
        }
        await self._save()
        driver = Driver(
            set_device=lambda on: self._set_device(entity_id, on),
            read_power=lambda: self.read_meter(meter),
            sleep=self.sleep,
            on_progress=self._on_progress,
            read_update=lambda: self.read_update(meter),
        )
        _LOGGER.info(
            "Measuring %s against %s: settle %ss, window %ss, %s cycle(s)",
            entity_id,
            meter,
            settings.settle_s,
            settings.window_s,
            settings.cycles,
        )
        try:
            windows = await run_sequence(settings, driver, entity_id)
        except asyncio.CancelledError:
            await self._end_run(entity_id, was_on and restore)
            self._finish(Progress(state=STATE_CANCELLED, entity_id=entity_id))
            raise
        except ProbeError as err:
            return await self._fail(entity_id, was_on and restore, err.code, err)
        except HomeAssistantError as err:
            _LOGGER.warning("Could not switch %s: %s", entity_id, err)
            return await self._fail(entity_id, was_on and restore, "command_failed")
        except Exception:
            _LOGGER.exception("Measurement of %s failed", entity_id)
            return await self._fail(entity_id, was_on and restore, "unknown")

        if await self._leave_device(entity_id, was_on and restore):
            self._active = None
        for window in windows:
            _LOGGER.info(
                "%s: %.1f W over %d readings (stdev %.1f)",
                window.step,
                window.mean,
                len(window.samples),
                window.stdev,
            )
        outcome = summarize(windows)
        record = self._record(
            entity_id, meter, settings, restore, started, windows, outcome
        )
        self.history.insert(0, record)
        del self.history[MAX_HISTORY:]
        await self._save()
        _LOGGER.info(
            "%s draws %.1f W (+/- %.1f, %s)",
            entity_id,
            outcome.power_w,
            outcome.uncertainty_w,
            outcome.quality,
        )
        self._finish(Progress(state=STATE_FINISHED, entity_id=entity_id, percent=100))
        self._notify(KIND_HISTORY)
        self.hass.bus.async_fire(
            EVENT_FINISHED,
            {"entity_id": entity_id, "success": True, "result": record},
        )
        return record

    def _record(
        self,
        entity_id: str,
        meter: str,
        settings: MeasureSettings,
        restore: bool,
        started: datetime,
        windows: list[Window],
        outcome: Outcome,
    ) -> dict[str, Any]:
        state = self.hass.states.get(entity_id)
        name = state.attributes.get("friendly_name") if state else None
        return {
            "id": uuid.uuid4().hex[:10],
            "entity_id": entity_id,
            "name": name or entity_id,
            "power_entity": meter,
            "started_at": started.isoformat(),
            "finished_at": dt_util.utcnow().isoformat(),
            "settings": settings.as_dict(),
            "restore_state": restore,
            **outcome.as_dict(),
            "windows": [window.as_dict() for window in windows],
            "powercalc_yaml": (
                None
                if outcome.power_w <= 0
                else powercalc_yaml(entity_id, outcome.power_w)
            ),
        }

    async def _fail(
        self,
        entity_id: str,
        restore_on: bool,
        code: str,
        err: ProbeError | None = None,
    ) -> dict[str, Any]:
        await self._end_run(entity_id, restore_on)
        self._finish(Progress(state=STATE_FAILED, entity_id=entity_id, error=code))
        details = err.placeholders if err else {}
        self.hass.bus.async_fire(
            EVENT_FINISHED,
            {"entity_id": entity_id, "success": False, "error": code, **details},
        )
        return {"error": code, "placeholders": details}

    async def _leave_device(self, entity_id: str, on: bool) -> bool:
        """End state: off, or back on if it was on and restore is enabled.

        True once the device is confirmed in that state.
        """
        try:
            await self._set_device(entity_id, on)
        except (ProbeError, HomeAssistantError) as err:
            _LOGGER.warning("Could not leave %s %s: %s", entity_id, on, err)
            return False
        return True

    async def _end_run(self, entity_id: str, on: bool) -> None:
        """Put the device back and, only if that is confirmed, forget the run."""
        if await self._leave_device(entity_id, on):
            self._active = None
            await self._save()

    @callback
    def _on_progress(self, progress: Progress) -> None:
        self.progress = progress
        self._notify(KIND_PROGRESS)

    @callback
    def _finish(self, progress: Progress) -> None:
        self.progress = progress
        self._notify(KIND_PROGRESS)

    # History ------------------------------------------------------------

    async def async_delete_result(self, result_id: str) -> bool:
        before = len(self.history)
        self.history = [r for r in self.history if r["id"] != result_id]
        if len(self.history) == before:
            return False
        await self._save()
        self._notify(KIND_HISTORY)
        return True


def get_manager(hass: HomeAssistant) -> ProbeManager:
    """The loaded entry's manager, or a translated error if none is set up."""
    entries = hass.config_entries.async_loaded_entries(DOMAIN)
    if not entries:
        raise ServiceValidationError(
            translation_domain=DOMAIN, translation_key="not_set_up"
        )
    return entries[0].runtime_data


def _state_matches(state: str, on: bool) -> bool:
    if on:
        return state not in (STATE_OFF, STATE_UNAVAILABLE, STATE_UNKNOWN)
    return state == STATE_OFF


def _validation_error(err: ProbeError) -> ServiceValidationError:
    return ServiceValidationError(
        translation_domain=DOMAIN,
        translation_key=err.code,
        translation_placeholders=err.placeholders or None,
    )
