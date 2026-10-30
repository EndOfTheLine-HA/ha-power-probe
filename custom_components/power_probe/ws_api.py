"""Websocket commands used by the sidebar panel."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError

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
from .manager import KIND_HISTORY, KIND_PROGRESS, get_manager


def _error_fields(err: HomeAssistantError) -> tuple[str, str]:
    """(code, message) for the panel. The code is the translation key."""
    return getattr(err, "translation_key", None) or "unknown", str(err)


@callback
def async_register_commands(hass: HomeAssistant) -> None:
    """Register every panel command."""
    websocket_api.async_register_command(hass, ws_info)
    websocket_api.async_register_command(hass, ws_start)
    websocket_api.async_register_command(hass, ws_cancel)
    websocket_api.async_register_command(hass, ws_delete)
    websocket_api.async_register_command(hass, ws_subscribe)


@websocket_api.require_admin
@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/info"})
@callback
def ws_info(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Defaults, presets, progress and saved results."""
    try:
        manager = get_manager(hass)
    except HomeAssistantError as err:
        code, message = _error_fields(err)
        connection.send_error(msg["id"], code, message)
        return
    connection.send_result(msg["id"], manager.info())


def _number(low: float, high: float) -> vol.All:
    return vol.All(vol.Coerce(float), vol.Range(min=low, max=high))


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/start",
        vol.Required("entity_id"): str,
        vol.Optional(CONF_POWER_ENTITY): str,
        vol.Optional(CONF_SETTLE): _number(MIN_SETTLE, MAX_SETTLE),
        vol.Optional(CONF_WINDOW): _number(MIN_WINDOW, MAX_WINDOW),
        vol.Optional(CONF_INTERVAL): _number(MIN_INTERVAL, MAX_INTERVAL),
        vol.Optional(CONF_CYCLES): vol.All(
            vol.Coerce(int), vol.Range(min=MIN_CYCLES, max=MAX_CYCLES)
        ),
        vol.Optional(CONF_RESTORE): bool,
    }
)
@callback
def ws_start(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Start a run. Progress arrives on the subscription."""
    options = {key: value for key, value in msg.items() if key not in ("id", "type")}
    entity_id = options.pop("entity_id")
    try:
        get_manager(hass).async_start(entity_id, options)
    except HomeAssistantError as err:
        code, message = _error_fields(err)
        connection.send_error(msg["id"], code, message)
        return
    connection.send_result(msg["id"])


@websocket_api.require_admin
@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/cancel"})
@websocket_api.async_response
async def ws_cancel(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Stop the run in progress."""
    try:
        cancelled = await get_manager(hass).async_cancel()
    except HomeAssistantError as err:
        code, message = _error_fields(err)
        connection.send_error(msg["id"], code, message)
        return
    connection.send_result(msg["id"], {"cancelled": cancelled})


@websocket_api.require_admin
@websocket_api.websocket_command(
    {vol.Required("type"): f"{DOMAIN}/delete", vol.Required("id_"): str}
)
@websocket_api.async_response
async def ws_delete(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Remove one saved result."""
    try:
        deleted = await get_manager(hass).async_delete_result(msg["id_"])
    except HomeAssistantError as err:
        code, message = _error_fields(err)
        connection.send_error(msg["id"], code, message)
        return
    connection.send_result(msg["id"], {"deleted": deleted})


@websocket_api.require_admin
@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/subscribe"})
@callback
def ws_subscribe(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Push progress every second of a run and the history when it changes."""
    try:
        manager = get_manager(hass)
    except HomeAssistantError as err:
        code, message = _error_fields(err)
        connection.send_error(msg["id"], code, message)
        return

    @callback
    def forward(kind: str) -> None:
        if kind == KIND_PROGRESS:
            payload: dict[str, Any] = {
                "kind": KIND_PROGRESS,
                "progress": manager.progress.as_dict(),
            }
        elif kind == KIND_HISTORY:
            payload = {"kind": KIND_HISTORY, "history": manager.history}
        else:
            return
        connection.send_message(websocket_api.event_message(msg["id"], payload))

    connection.subscriptions[msg["id"]] = manager.add_listener(forward)
    connection.send_result(msg["id"])
    forward(KIND_PROGRESS)
    forward(KIND_HISTORY)
