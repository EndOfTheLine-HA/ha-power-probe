"""Status and last-result sensors."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
)
from homeassistant.const import UnitOfPower
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import DOMAIN, STATES
from .manager import KIND_HISTORY, ProbeConfigEntry, ProbeManager

PARALLEL_UPDATES = 0

RESULT_ATTRIBUTES = (
    "entity_id",
    "quality",
    "limiting",
    "uncertainty_w",
    "off_start_w",
    "on_w",
    "off_end_w",
    "drift_w",
    "finished_at",
    "powercalc_yaml",
)
PROGRESS_ATTRIBUTES = (
    "entity_id",
    "step",
    "activity",
    "percent",
    "seconds_left",
    "latest_w",
    "error",
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ProbeConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the two sensors."""
    manager = entry.runtime_data
    async_add_entities(
        [
            ProbeStatusSensor(manager, entry),
            ProbeLastResultSensor(manager, entry),
        ]
    )


class _ProbeSensor(SensorEntity):
    """Base: pushed by the manager, never polled."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    # Only history changes matter to this sensor unless a subclass says more.
    _kinds: tuple[str, ...] = (KIND_HISTORY,)

    def __init__(self, manager: ProbeManager, entry: ProbeConfigEntry, key: str):
        self._manager = manager
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_translation_key = key
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            entry_type=DeviceEntryType.SERVICE,
            manufacturer="Power Probe",
            name="Power Probe",
        )

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self._manager.add_listener(self._handle))

    @callback
    def _handle(self, kind: str) -> None:
        if kind in self._kinds:
            self.async_write_ha_state()


class ProbeStatusSensor(_ProbeSensor):
    """What the probe is doing now, with progress in the attributes."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = list(STATES)
    _kinds = ("progress", KIND_HISTORY)

    def __init__(self, manager: ProbeManager, entry: ProbeConfigEntry) -> None:
        super().__init__(manager, entry, "status")

    @property
    def native_value(self) -> str:
        return self._manager.progress.state

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        progress = self._manager.progress.as_dict()
        return {key: progress[key] for key in PROGRESS_ATTRIBUTES}


class ProbeLastResultSensor(_ProbeSensor):
    """The draw found by the latest finished run, in watts."""

    _attr_device_class = SensorDeviceClass.POWER
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_suggested_display_precision = 1

    def __init__(self, manager: ProbeManager, entry: ProbeConfigEntry) -> None:
        super().__init__(manager, entry, "last_result")

    @property
    def native_value(self) -> float | None:
        result = self._manager.last_result
        return result["power_w"] if result else None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        result = self._manager.last_result
        if result is None:
            return None
        return {key: result.get(key) for key in RESULT_ATTRIBUTES}
