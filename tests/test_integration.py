"""Real HA flows, services, sensors and lifecycle, with a fake house."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.exceptions import (
    HomeAssistantError,
    ServiceValidationError,
    Unauthorized,
)
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.storage import Store

from custom_components.power_probe import panel as panel_module
from custom_components.power_probe import ws_api
from custom_components.power_probe.const import DOMAIN, EVENT_FINISHED
from tests.conftest import DEVICE, METER, House

FAST_RUN = {
    "entity_id": DEVICE,
    "settle_time": 1,
    "sample_window": 6,
    "sample_interval": 2,
}


async def add_probe(hass, house=None, profile="fast", **extra):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    assert result["step_id"] == "user"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            "power_entity": METER,
            "timing_profile": profile,
            "cycles": 1,
            "restore_state": True,
            **extra,
        },
    )
    assert result["type"] == "create_entry", result
    await hass.async_block_till_done()
    entry = result["result"]
    if house is not None:
        entry.runtime_data.sleep = house.sleep
    return entry


async def run_with_response(hass, **data):
    return await hass.services.async_call(
        DOMAIN,
        "start_measurement",
        {**FAST_RUN, **data},
        blocking=True,
        return_response=True,
    )


def events(hass):
    seen = []
    hass.bus.async_listen(EVENT_FINISHED, lambda event: seen.append(event.data))
    return seen


async def test_config_flow_creates_entry_sensors_and_unloads(hass, house):
    entry = await add_probe(hass, house)
    assert entry.state is ConfigEntryState.LOADED
    assert entry.title == "Power Probe"
    assert entry.data == {}
    assert entry.options == {
        "power_entity": METER,
        "timing_profile": "fast",
        "cycles": 1,
        "restore_state": True,
    }
    registry = er.async_get(hass)
    ids = sorted(
        e.entity_id for e in er.async_entries_for_config_entry(registry, entry.entry_id)
    )
    assert ids == [
        "sensor.power_probe_last_measured_power",
        "sensor.power_probe_status",
    ]
    assert hass.states.get("sensor.power_probe_status").state == "idle"
    assert hass.states.get("sensor.power_probe_last_measured_power").state == "unknown"

    assert await hass.config_entries.async_unload(entry.entry_id)
    assert entry.state is ConfigEntryState.NOT_LOADED


async def test_only_one_entry_is_allowed(hass, house):
    await add_probe(hass, house)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    assert result["type"] == "abort"
    assert result["reason"] == "single_instance_allowed"


async def test_custom_timing_is_asked_only_for_custom_and_validated(hass, house):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            "power_entity": METER,
            "timing_profile": "custom",
            "cycles": 2.0,
            "restore_state": False,
        },
    )
    assert result["step_id"] == "timing"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"settle_time": 10.0, "sample_window": 20.0, "sample_interval": 30.0},
    )
    assert result["step_id"] == "timing"
    assert result["errors"] == {"sample_interval": "interval_longer_than_window"}
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"settle_time": 10.0, "sample_window": 20.0, "sample_interval": 5.0},
    )
    assert result["type"] == "create_entry"
    assert result["options"] == {
        "power_entity": METER,
        "timing_profile": "custom",
        "cycles": 2,
        "restore_state": False,
        "settle_time": 10,
        "sample_window": 20,
        "sample_interval": 5,
    }
    settings = result["result"].runtime_data.default_settings()
    assert (settings.settle_s, settings.window_s, settings.interval_s) == (10, 20, 5)
    assert settings.cycles == 2


async def test_options_flow_changes_defaults_and_reloads(hass, house):
    entry = await add_probe(hass, house)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["step_id"] == "init"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "power_entity": METER,
            "timing_profile": "slow",
            "cycles": 3.0,
            "restore_state": False,
        },
    )
    assert result["type"] == "create_entry"
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    settings = entry.runtime_data.default_settings()
    assert (settings.settle_s, settings.window_s, settings.cycles) == (120, 150, 3)
    assert entry.runtime_data.default_restore is False


async def test_full_run_returns_the_device_power(hass, house):
    seen = events(hass)
    await add_probe(hass, house)
    result = await run_with_response(hass)

    assert result["entity_id"] == DEVICE
    assert result["name"] == "Heater"
    assert result["power_entity"] == METER
    assert result["power_w"] == 60.0
    assert result["quality"] == "good"
    assert [w["step"] for w in result["windows"]] == ["off_1", "on_1", "off_2"]
    assert [w["mean_w"] for w in result["windows"]] == [250.0, 310.0, 250.0]
    assert result["off_start_w"] == 250.0
    assert result["on_w"] == 310.0
    assert result["off_end_w"] == 250.0
    assert "power: 60" in result["powercalc_yaml"]
    assert "entity_id: switch.heater" in result["powercalc_yaml"]

    # Off, on, off, and the device was off to begin with so it stays off.
    assert house.commands == [(DEVICE, "off"), (DEVICE, "on"), (DEVICE, "off")] + [
        (DEVICE, "off")
    ]
    assert hass.states.get(DEVICE).state == "off"

    await hass.async_block_till_done()
    status = hass.states.get("sensor.power_probe_status")
    assert status.state == "finished"
    last = hass.states.get("sensor.power_probe_last_measured_power")
    assert float(last.state) == 60.0
    assert last.attributes["unit_of_measurement"] == "W"
    assert last.attributes["entity_id"] == DEVICE
    assert last.attributes["quality"] == "good"
    assert "power: 60" in last.attributes["powercalc_yaml"]
    assert seen[0]["success"] is True
    assert seen[0]["result"]["power_w"] == 60.0


async def test_start_without_response_returns_at_once_and_finishes_later(hass, house):
    entry = await add_probe(hass, house)
    response = await hass.services.async_call(
        DOMAIN, "start_measurement", FAST_RUN, blocking=True
    )
    assert response is None
    await hass.async_block_till_done(wait_background_tasks=True)
    assert entry.runtime_data.last_result["power_w"] == 60.0
    assert hass.states.get("sensor.power_probe_status").state == "finished"


async def test_device_that_was_on_is_restored_unless_told_not_to(hass, house):
    await add_probe(hass, house)
    house.on = True
    house.publish_device()
    house.publish()
    await run_with_response(hass)
    assert hass.states.get(DEVICE).state == "on"

    await run_with_response(hass, restore_state=False)
    assert hass.states.get(DEVICE).state == "off"


async def test_kilowatt_meter_is_converted(hass):
    house = House(hass, base=0.25, device=0.06, unit="kW")
    house.base, house.device = 250.0, 60.0
    house.publish()
    await add_probe(hass, house)
    result = await run_with_response(hass)
    assert result["power_w"] == 60.0
    assert result["off_start_w"] == 250.0


async def test_meter_can_be_overridden_per_run(hass, house):
    await add_probe(hass, house)
    hass.states.async_set(
        "sensor.other_meter",
        "1000",
        {"unit_of_measurement": "W", "device_class": "power"},
    )
    # The other meter never moves, so the run is flat and inconclusive.
    result = await run_with_response(hass, power_entity="sensor.other_meter")
    assert result["power_entity"] == "sensor.other_meter"
    assert result["quality"] == "inconclusive"
    assert "meter_not_updating" in result["warnings"]


async def test_two_cycles_run_five_steps(hass, house):
    await add_probe(hass, house)
    result = await run_with_response(hass, cycles=2)
    assert len(result["windows"]) == 5
    assert len(result["cycle_deltas_w"]) == 2
    assert result["power_w"] == 60.0


async def test_cancel_stops_the_run_and_puts_the_device_back(hass, house):
    entry = await add_probe(hass, house)
    seen = events(hass)
    gate = asyncio.Event()
    reached_on = asyncio.Event()

    async def stall(_t):
        if house.on:
            reached_on.set()
            await gate.wait()

    house.on_sleep = stall
    await hass.services.async_call(DOMAIN, "start_measurement", FAST_RUN, blocking=True)
    await asyncio.wait_for(reached_on.wait(), 2)
    assert hass.states.get("sensor.power_probe_status").state == "measuring"
    assert hass.states.get(DEVICE).state == "on"

    await hass.services.async_call(DOMAIN, "cancel_measurement", {}, blocking=True)
    await hass.async_block_till_done()
    assert hass.states.get("sensor.power_probe_status").state == "cancelled"
    assert hass.states.get(DEVICE).state == "off"
    assert entry.runtime_data.history == []
    assert not entry.runtime_data.busy
    assert seen == []


async def test_second_start_while_busy_is_refused(hass, house):
    await add_probe(hass, house)
    gate = asyncio.Event()

    async def stall(_t):
        await gate.wait()

    house.on_sleep = stall
    await hass.services.async_call(DOMAIN, "start_measurement", FAST_RUN, blocking=True)
    with pytest.raises(ServiceValidationError) as raised:
        await hass.services.async_call(
            DOMAIN, "start_measurement", FAST_RUN, blocking=True
        )
    assert raised.value.translation_key == "busy"
    gate.set()
    await hass.async_block_till_done(wait_background_tasks=True)


@pytest.mark.parametrize(
    ("data", "key"),
    [
        ({"entity_id": METER}, "device_not_supported"),
        ({"entity_id": "button.doorbell"}, "device_not_supported"),
        ({"entity_id": "switch.missing"}, "device_unavailable"),
        ({"power_entity": "sensor.missing"}, "meter_unavailable"),
        ({"power_entity": "sensor.energy_total"}, "meter_not_power"),
        ({"sample_interval": 10, "sample_window": 5}, "interval_longer_than_window"),
    ],
)
async def test_bad_requests_are_refused_with_a_translation_key(hass, house, data, key):
    await add_probe(hass, house)
    hass.states.async_set("button.doorbell", "unknown")
    hass.states.async_set("sensor.energy_total", "5", {"unit_of_measurement": "kWh"})
    with pytest.raises(ServiceValidationError) as raised:
        await hass.services.async_call(
            DOMAIN, "start_measurement", {**FAST_RUN, **data}, blocking=True
        )
    assert raised.value.translation_domain == DOMAIN
    assert raised.value.translation_key == key
    # Refused before anything was switched.
    assert house.commands == []


async def test_unavailable_meter_is_refused(hass, house):
    await add_probe(hass, house)
    hass.states.async_set(METER, "unavailable", {"unit_of_measurement": "W"})
    with pytest.raises(ServiceValidationError) as raised:
        await hass.services.async_call(
            DOMAIN, "start_measurement", FAST_RUN, blocking=True
        )
    assert raised.value.translation_key == "meter_unavailable"


async def test_device_that_ignores_commands_fails_cleanly(hass, house):
    await add_probe(hass, house)
    seen = events(hass)
    house.obeys = False
    with pytest.raises(HomeAssistantError) as raised:
        await run_with_response(hass)
    assert raised.value.translation_key == "device_did_not_change"
    await hass.async_block_till_done()
    assert hass.states.get("sensor.power_probe_status").state == "failed"
    assert (
        hass.states.get("sensor.power_probe_status").attributes["error"]
        == "device_did_not_change"
    )
    assert seen[0]["success"] is False
    assert seen[0]["error"] == "device_did_not_change"


async def test_meter_dying_mid_run_fails_and_leaves_the_device_off(hass, house):
    entry = await add_probe(hass, house)

    def kill(_t):
        if house.on:
            hass.states.async_set(METER, "unavailable", {"unit_of_measurement": "W"})

    house.on_sleep = kill
    with pytest.raises(HomeAssistantError) as raised:
        await run_with_response(hass)
    assert raised.value.translation_key == "meter_unavailable_during_run"
    assert hass.states.get(DEVICE).state == "off"
    assert entry.runtime_data.history == []


async def test_history_survives_reload_and_can_be_deleted(hass, house):
    entry = await add_probe(hass, house)
    await run_with_response(hass)
    await run_with_response(hass, cycles=2)
    assert len(entry.runtime_data.history) == 2

    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    manager = entry.runtime_data
    assert len(manager.history) == 2
    assert manager.last_result["settings"]["cycles"] == 2
    assert float(hass.states.get("sensor.power_probe_last_measured_power").state) == 60

    newest = manager.history[0]["id"]
    assert await manager.async_delete_result(newest)
    assert not await manager.async_delete_result(newest)
    assert len(manager.history) == 1


async def test_history_is_capped(hass, house):
    from custom_components.power_probe.const import MAX_HISTORY

    entry = await add_probe(hass, house)
    manager = entry.runtime_data
    manager.history = [{"id": str(i), "power_w": 1} for i in range(MAX_HISTORY)]
    await run_with_response(hass)
    assert len(manager.history) == MAX_HISTORY
    assert manager.history[0]["power_w"] == 60.0


async def test_services_fail_clearly_when_not_set_up(hass):
    from custom_components.power_probe import async_setup

    assert await async_setup(hass, {})
    with pytest.raises(ServiceValidationError) as raised:
        await hass.services.async_call(DOMAIN, "cancel_measurement", {}, blocking=True)
    assert raised.value.translation_key == "not_set_up"


# Websocket handlers, called the way Home Assistant's websocket API calls them.


class FakeConnection:
    def __init__(self, admin: bool = True) -> None:
        self.user = MagicMock(is_admin=admin)
        self.results: list[tuple] = []
        self.errors: list[tuple] = []
        self.sent: list[dict] = []
        self.subscriptions: dict = {}

    def send_result(self, msg_id, result=None):
        self.results.append((msg_id, result))

    def send_error(self, msg_id, code, message):
        self.errors.append((msg_id, code, message))

    def send_message(self, message):
        self.sent.append(message)


async def test_websocket_info_start_subscribe_cancel_delete(hass, house):
    entry = await add_probe(hass, house)
    manager = entry.runtime_data
    conn = FakeConnection()

    ws_api.ws_info(hass, conn, {"id": 1, "type": "power_probe/info"})
    info = conn.results[-1][1]
    assert info["power_entity"] == METER
    assert info["settings"] == {
        "settle_s": 15.0,
        "window_s": 20.0,
        "interval_s": 2.0,
        "cycles": 1,
    }
    assert info["profiles"]["slow"] == {
        "settle_s": 120,
        "window_s": 150,
        "interval_s": 5,
    }
    assert "switch" in info["supported_domains"]
    assert info["history"] == []

    ws_api.ws_subscribe(hass, conn, {"id": 2, "type": "power_probe/subscribe"})
    assert conn.results[-1] == (2, None)
    assert [m["event"]["kind"] for m in conn.sent] == ["progress", "history"]
    assert 2 in conn.subscriptions

    ws_api.ws_start(
        hass,
        conn,
        {
            "id": 3,
            "type": "power_probe/start",
            "entity_id": DEVICE,
            "settle_time": 1,
            "sample_window": 6,
            "sample_interval": 2,
        },
    )
    assert conn.results[-1] == (3, None)
    await hass.async_block_till_done(wait_background_tasks=True)
    kinds = [m["event"]["kind"] for m in conn.sent]
    assert "history" in kinds[2:]
    progress = [
        m["event"]["progress"] for m in conn.sent if m["event"]["kind"] == "progress"
    ]
    assert progress[-1]["state"] == "finished"
    assert any(p["state"] == "measuring" and p["step"] == "on_1" for p in progress)
    latest = [
        m["event"]["history"] for m in conn.sent if m["event"]["kind"] == "history"
    ][-1]
    assert latest[0]["power_w"] == 60.0

    # Starting again with a bad entity reports the translation key.
    ws_api.ws_start(
        hass, conn, {"id": 4, "type": "power_probe/start", "entity_id": METER}
    )
    assert conn.errors[-1][:2] == (4, "device_not_supported")

    # async_response runs these as background tasks.
    ws_api.ws_delete(
        hass, conn, {"id": 5, "type": "power_probe/delete", "id_": latest[0]["id"]}
    )
    await hass.async_block_till_done(wait_background_tasks=True)
    assert conn.results[-1] == (5, {"deleted": True})
    ws_api.ws_cancel(hass, conn, {"id": 6, "type": "power_probe/cancel"})
    await hass.async_block_till_done(wait_background_tasks=True)
    assert conn.results[-1] == (6, {"cancelled": False})

    # Unsubscribing stops the pushes.
    conn.subscriptions[2]()
    before = len(conn.sent)
    manager._notify("progress")
    assert len(conn.sent) == before


async def test_websocket_commands_report_when_not_set_up(hass):
    conn = FakeConnection()
    ws_api.ws_info(hass, conn, {"id": 1, "type": "power_probe/info"})
    assert conn.errors[-1][:2] == (1, "not_set_up")
    ws_api.ws_subscribe(hass, conn, {"id": 2, "type": "power_probe/subscribe"})
    assert conn.errors[-1][:2] == (2, "not_set_up")


async def test_websocket_commands_are_admin_only(hass, house):
    await add_probe(hass, house)
    conn = FakeConnection(admin=False)
    for handler, msg in (
        (ws_api.ws_info, {"id": 1, "type": "power_probe/info"}),
        (ws_api.ws_subscribe, {"id": 2, "type": "power_probe/subscribe"}),
        (ws_api.ws_start, {"id": 3, "type": "power_probe/start", "entity_id": DEVICE}),
    ):
        with pytest.raises(Unauthorized):
            handler(hass, conn, msg)
    for handler, msg in (
        (ws_api.ws_cancel, {"id": 4, "type": "power_probe/cancel"}),
        (ws_api.ws_delete, {"id": 5, "type": "power_probe/delete", "id_": "x"}),
    ):
        with pytest.raises(Unauthorized):
            handler(hass, conn, msg)
    assert conn.results == []
    assert house.commands == []


async def test_commands_register_with_the_websocket_api(hass):
    with patch.object(ws_api.websocket_api, "async_register_command") as register:
        ws_api.async_register_commands(hass)
    assert register.call_count == 5


# The panel module, with the web server and frontend replaced.


async def test_panel_is_registered_once_for_admins_only(hass):
    hass.http = MagicMock(async_register_static_paths=AsyncMock())
    with (
        patch.object(
            panel_module.panel_custom, "async_register_panel", new=AsyncMock()
        ) as register,
        patch.object(panel_module.frontend, "async_remove_panel") as remove,
    ):
        await panel_module.async_register_panel(hass)
        await panel_module.async_register_panel(hass)
        panel_module.async_remove_panel(hass)

    assert hass.http.async_register_static_paths.await_count == 1
    (config,) = hass.http.async_register_static_paths.await_args.args[0]
    assert config.url_path == "/power_probe_static"
    assert (panel_module.FRONTEND_DIR / panel_module.MODULE_FILE).is_file()
    assert register.await_count == 2
    kwargs = register.await_args.kwargs
    assert kwargs["require_admin"] is True
    assert kwargs["frontend_url_path"] == "power-probe"
    assert kwargs["webcomponent_name"] == "power-probe-panel"
    assert kwargs["module_url"].startswith(
        "/power_probe_static/power-probe-panel.js?v="
    )
    # Removed before each registration and again on unload.
    assert remove.call_count == 3


# A restart or power cut mid-run must not leave the device switched.


def stored(hass):
    """What is on disk, read directly so a cached copy cannot hide a bug."""
    path = Path(hass.config.path(".storage", "power_probe.history"))
    return json.loads(path.read_text(encoding="utf-8"))["data"]


async def seed_interrupted_run(hass, final_on):
    await Store(hass, 1, "power_probe.history").async_save(
        {
            "history": [],
            "active": {
                "entity_id": DEVICE,
                "final_on": final_on,
                "started_at": "2026-10-30T09:00:00+00:00",
            },
        }
    )


async def start_when_started(hass):
    hass.bus.async_fire(EVENT_HOMEASSISTANT_STARTED)
    await hass.async_block_till_done(wait_background_tasks=True)


async def test_marker_is_saved_before_switching_and_cleared_when_done(hass, house):
    entry = await add_probe(hass, house)
    manager = entry.runtime_data
    manager.history = [{"id": "seed", "power_w": 1}]
    gate = asyncio.Event()
    reached_on = asyncio.Event()

    async def stall(_t):
        if house.on:
            reached_on.set()
            await gate.wait()

    house.on_sleep = stall
    await hass.services.async_call(DOMAIN, "start_measurement", FAST_RUN, blocking=True)
    await asyncio.wait_for(reached_on.wait(), 2)
    assert stored(hass)["active"] == {
        "entity_id": DEVICE,
        "final_on": False,
        "started_at": stored(hass)["active"]["started_at"],
    }
    # Deleting a saved result mid-run must not drop the marker.
    assert await manager.async_delete_result("seed")
    assert stored(hass)["active"]["entity_id"] == DEVICE

    gate.set()
    await hass.async_block_till_done(wait_background_tasks=True)
    assert stored(hass)["active"] is None
    assert manager.last_result["power_w"] == 60.0


async def test_cancel_and_a_failed_run_both_clear_the_marker(hass, house):
    entry = await add_probe(hass, house)
    gate = asyncio.Event()
    reached_on = asyncio.Event()

    async def stall(_t):
        if house.on:
            reached_on.set()
            await gate.wait()

    house.on_sleep = stall
    await hass.services.async_call(DOMAIN, "start_measurement", FAST_RUN, blocking=True)
    await asyncio.wait_for(reached_on.wait(), 2)
    await hass.services.async_call(DOMAIN, "cancel_measurement", {}, blocking=True)
    assert stored(hass)["active"] is None
    assert hass.states.get(DEVICE).state == "off"

    house.on_sleep = lambda _t: (
        hass.states.async_set(METER, "unavailable", {"unit_of_measurement": "W"})
        if house.on
        else None
    )
    with pytest.raises(HomeAssistantError):
        await run_with_response(hass)
    assert hass.states.get(DEVICE).state == "off"
    assert stored(hass)["active"] is None
    assert not entry.runtime_data.busy


async def test_marker_stays_when_the_device_cannot_be_put_back(hass, house):
    entry = await add_probe(hass, house)
    gate = asyncio.Event()
    reached_on = asyncio.Event()

    async def stall(_t):
        if house.on:
            reached_on.set()
            await gate.wait()

    house.on_sleep = stall
    await hass.services.async_call(DOMAIN, "start_measurement", FAST_RUN, blocking=True)
    await asyncio.wait_for(reached_on.wait(), 2)
    # The device stops answering while it is on, then the run is cancelled.
    house.obeys = False
    house.on_sleep = None
    await entry.runtime_data.async_cancel()
    assert hass.states.get(DEVICE).state == "on"
    assert stored(hass)["active"]["entity_id"] == DEVICE


@pytest.mark.parametrize(
    ("final_on", "start_on", "end_state"),
    [(False, True, "off"), (True, False, "on")],
)
async def test_interrupted_run_is_put_back_once_ha_has_started(
    hass, house, final_on, start_on, end_state
):
    seen = events(hass)
    # The device is stuck the way a crash would leave it.
    house.on = start_on
    house.publish_device()
    house.publish()
    await seed_interrupted_run(hass, final_on)
    entry = await add_probe(hass, house)
    # Nothing is touched while Home Assistant is still starting.
    assert house.commands == []
    assert entry.runtime_data.progress.state == "idle"

    await start_when_started(hass)
    assert hass.states.get(DEVICE).state == end_state
    assert stored(hass)["active"] is None
    assert entry.runtime_data.progress.state == "failed"
    assert entry.runtime_data.progress.error == "interrupted"
    assert hass.states.get("sensor.power_probe_status").state == "failed"
    assert seen == [{"entity_id": DEVICE, "success": False, "error": "interrupted"}]


async def test_interrupted_run_is_retried_if_the_device_will_not_answer(hass, house):
    house.on = True
    house.publish_device()
    house.publish()
    house.obeys = False
    await seed_interrupted_run(hass, False)
    entry = await add_probe(hass, house)
    await start_when_started(hass)
    assert hass.states.get(DEVICE).state == "on"
    assert stored(hass)["active"]["entity_id"] == DEVICE
    assert entry.runtime_data.progress.error == "interrupted"


async def test_nothing_happens_at_startup_without_an_interrupted_run(hass, house):
    entry = await add_probe(hass, house)
    await start_when_started(hass)
    assert house.commands == []
    assert entry.runtime_data.progress.state == "idle"
