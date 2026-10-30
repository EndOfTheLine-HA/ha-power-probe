"""Config flow for Power Probe."""

from __future__ import annotations

from typing import Any, override

import voluptuous as vol
from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    BooleanSelector,
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

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
    MAX_CYCLES,
    MAX_INTERVAL,
    MAX_SETTLE,
    MAX_WINDOW,
    MIN_CYCLES,
    MIN_INTERVAL,
    MIN_SETTLE,
    MIN_WINDOW,
    PROFILE_CUSTOM,
    PROFILES,
)


def _seconds(low: int, high: int) -> NumberSelector:
    return NumberSelector(
        NumberSelectorConfig(
            min=low,
            max=high,
            step=1,
            unit_of_measurement="s",
            mode=NumberSelectorMode.BOX,
        )
    )


MAIN_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_POWER_ENTITY): EntitySelector(
            EntitySelectorConfig(domain="sensor", device_class=SensorDeviceClass.POWER)
        ),
        vol.Required(CONF_PROFILE, default=DEFAULT_PROFILE): SelectSelector(
            SelectSelectorConfig(
                options=list(PROFILES),
                translation_key="timing_profile",
                mode=SelectSelectorMode.DROPDOWN,
            )
        ),
        vol.Required(CONF_CYCLES, default=DEFAULT_CYCLES): NumberSelector(
            NumberSelectorConfig(
                min=MIN_CYCLES,
                max=MAX_CYCLES,
                step=1,
                mode=NumberSelectorMode.BOX,
            )
        ),
        vol.Required(CONF_RESTORE, default=DEFAULT_RESTORE): BooleanSelector(),
    }
)

TIMING_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_SETTLE, default=DEFAULT_CUSTOM_TIMING[0]): _seconds(
            MIN_SETTLE, MAX_SETTLE
        ),
        vol.Required(CONF_WINDOW, default=DEFAULT_CUSTOM_TIMING[1]): _seconds(
            MIN_WINDOW, MAX_WINDOW
        ),
        vol.Required(CONF_INTERVAL, default=DEFAULT_CUSTOM_TIMING[2]): _seconds(
            MIN_INTERVAL, MAX_INTERVAL
        ),
    }
)


def timing_errors(user_input: dict[str, Any]) -> dict[str, str]:
    """Errors for the custom timing form."""
    if user_input[CONF_INTERVAL] > user_input[CONF_WINDOW]:
        return {CONF_INTERVAL: "interval_longer_than_window"}
    return {}


def build_options(
    main: dict[str, Any], timing: dict[str, Any] | None
) -> dict[str, Any]:
    """Stored options from the two forms. Number selectors give floats."""
    options: dict[str, Any] = {
        CONF_POWER_ENTITY: main[CONF_POWER_ENTITY],
        CONF_PROFILE: main[CONF_PROFILE],
        CONF_CYCLES: int(main[CONF_CYCLES]),
        CONF_RESTORE: bool(main[CONF_RESTORE]),
    }
    if main[CONF_PROFILE] == PROFILE_CUSTOM and timing is not None:
        options |= {key: int(timing[key]) for key in (CONF_SETTLE, CONF_WINDOW)}
        options[CONF_INTERVAL] = int(timing[CONF_INTERVAL])
    return options


class _SettingsSteps:
    """The two forms, shared by the config flow and the options flow.

    The host flow keeps the first form's answers in `_main`, may offer current
    values through `_current`, and saves the finished options in `_finish`.
    """

    _main: dict[str, Any]

    def _current(self) -> dict[str, Any]:
        return {}

    def _finish(self, options: dict[str, Any]) -> ConfigFlowResult:
        raise NotImplementedError

    async def _async_main(
        self, step_id: str, user_input: dict[str, Any] | None
    ) -> ConfigFlowResult:
        if user_input is not None:
            self._main = user_input
            if user_input[CONF_PROFILE] == PROFILE_CUSTOM:
                return await self.async_step_timing()  # type: ignore[attr-defined]
            return self._finish(build_options(user_input, None))
        return self.async_show_form(  # type: ignore[attr-defined]
            step_id=step_id,
            data_schema=self.add_suggested_values_to_schema(  # type: ignore[attr-defined]
                MAIN_SCHEMA, self._current()
            ),
        )

    async def async_step_timing(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Custom timing, asked only when the profile is custom."""
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = timing_errors(user_input)
            if not errors:
                return self._finish(build_options(self._main, user_input))
        return self.async_show_form(  # type: ignore[attr-defined]
            step_id="timing",
            data_schema=self.add_suggested_values_to_schema(  # type: ignore[attr-defined]
                TIMING_SCHEMA, user_input or self._current()
            ),
            errors=errors,
        )


class PowerProbeConfigFlow(_SettingsSteps, ConfigFlow, domain=DOMAIN):
    """Set up Power Probe. One entry; the meter can still be changed per run."""

    VERSION = 1

    def __init__(self) -> None:
        self._main = {}

    @override
    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return await self._async_main("user", user_input)

    def _finish(self, options: dict[str, Any]) -> ConfigFlowResult:
        return self.async_create_entry(title="Power Probe", data={}, options=options)

    @staticmethod
    @callback
    @override
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return PowerProbeOptionsFlow()


class PowerProbeOptionsFlow(_SettingsSteps, OptionsFlow):
    """Change the default meter, timing, cycles and restore behaviour."""

    def __init__(self) -> None:
        self._main = {}

    def _current(self) -> dict[str, Any]:
        return dict(self.config_entry.options)

    def _finish(self, options: dict[str, Any]) -> ConfigFlowResult:
        return self.async_create_entry(data=options)

    @override
    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return await self._async_main("init", user_input)
