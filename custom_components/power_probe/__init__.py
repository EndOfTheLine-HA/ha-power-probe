"""Power Probe: measure a device's draw with the whole-home meter you have."""

from __future__ import annotations

import voluptuous as vol
from homeassistant.const import ATTR_ENTITY_ID, Platform
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
)
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.start import async_at_started
from homeassistant.helpers.typing import ConfigType

from .const import (
    CONF_CYCLES,
    CONF_INTERVAL,
    CONF_POWER_ENTITY,
    CONF_RESTORE,
    CONF_SETTLE,
    CONF_WINDOW,
    DOMAIN,
    MAX_CYCLES,
    MAX_INTERVAL,
    MAX_SETTLE,
    MAX_WINDOW,
    MIN_CYCLES,
    MIN_INTERVAL,
    MIN_SETTLE,
    MIN_WINDOW,
)
from .manager import ProbeConfigEntry, ProbeManager, get_manager
from .panel import async_register_panel, async_remove_panel
from .ws_api import async_register_commands

PLATFORMS = [Platform.SENSOR]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

SERVICE_START = "start_measurement"
SERVICE_CANCEL = "cancel_measurement"


def _seconds(low: int, high: int) -> vol.All:
    return vol.All(vol.Coerce(float), vol.Range(min=low, max=high))


START_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_ENTITY_ID): cv.entity_id,
        vol.Optional(CONF_POWER_ENTITY): cv.entity_id,
        vol.Optional(CONF_SETTLE): _seconds(MIN_SETTLE, MAX_SETTLE),
        vol.Optional(CONF_WINDOW): _seconds(MIN_WINDOW, MAX_WINDOW),
        vol.Optional(CONF_INTERVAL): _seconds(MIN_INTERVAL, MAX_INTERVAL),
        vol.Optional(CONF_CYCLES): vol.All(
            vol.Coerce(int), vol.Range(min=MIN_CYCLES, max=MAX_CYCLES)
        ),
        vol.Optional(CONF_RESTORE): cv.boolean,
    }
)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the actions and websocket commands once per Home Assistant."""

    async def start_measurement(call: ServiceCall) -> ServiceResponse:
        """Start a run. With a response variable, wait and return the result."""
        manager = get_manager(hass)
        options = dict(call.data)
        entity_id = options.pop(ATTR_ENTITY_ID)
        task = manager.async_start(entity_id, options)
        if not call.return_response:
            return None
        # No shield: stopping the caller cancels the run, which puts the
        # device back as it found it.
        result = await task
        if "error" in result:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key=result["error"],
                translation_placeholders=result.get("placeholders") or None,
            )
        return result

    async def cancel_measurement(call: ServiceCall) -> None:
        await get_manager(hass).async_cancel()

    hass.services.async_register(
        DOMAIN,
        SERVICE_START,
        start_measurement,
        schema=START_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(DOMAIN, SERVICE_CANCEL, cancel_measurement)
    async_register_commands(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ProbeConfigEntry) -> bool:
    """Set up Power Probe: history, sensors and the sidebar panel."""
    manager = ProbeManager(hass, entry)
    await manager.async_load()
    entry.runtime_data = manager
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    await async_register_panel(hass)

    # A restart or power cut in the middle of a run can leave the device
    # switched. Once everything has started, put it back.
    async def recover(_hass: HomeAssistant) -> None:
        entry.async_create_background_task(
            hass, manager.async_recover(), name=f"{DOMAIN} recover interrupted run"
        )

    entry.async_on_unload(async_at_started(hass, recover))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ProbeConfigEntry) -> bool:
    """Stop any run, which restores the device, then unload."""
    await entry.runtime_data.async_cancel()
    async_remove_panel(hass)
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_reload_entry(hass: HomeAssistant, entry: ProbeConfigEntry) -> None:
    """Reload after options change."""
    await hass.config_entries.async_reload(entry.entry_id)
