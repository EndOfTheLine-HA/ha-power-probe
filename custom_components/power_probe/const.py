"""Constants for Power Probe."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "power_probe"
VERSION: Final = "0.1.0"

# Config entry data and options.
CONF_POWER_ENTITY: Final = "power_entity"
CONF_PROFILE: Final = "timing_profile"
CONF_SETTLE: Final = "settle_time"
CONF_WINDOW: Final = "sample_window"
CONF_INTERVAL: Final = "sample_interval"
CONF_CYCLES: Final = "cycles"
CONF_RESTORE: Final = "restore_state"

PROFILE_FAST: Final = "fast"
PROFILE_MEDIUM: Final = "medium"
PROFILE_SLOW: Final = "slow"
PROFILE_CUSTOM: Final = "custom"
PROFILES: Final = (PROFILE_FAST, PROFILE_MEDIUM, PROFILE_SLOW, PROFILE_CUSTOM)

# (settle seconds, sample window seconds, sample interval seconds).
# Settle must outlast the meter's update interval, or the first readings of a
# step still show the previous state.
PROFILE_TIMINGS: Final[dict[str, tuple[int, int, int]]] = {
    PROFILE_FAST: (15, 20, 2),
    PROFILE_MEDIUM: (45, 60, 5),
    PROFILE_SLOW: (120, 150, 5),
}

DEFAULT_PROFILE: Final = PROFILE_MEDIUM
DEFAULT_CUSTOM_TIMING: Final = PROFILE_TIMINGS[PROFILE_MEDIUM]
DEFAULT_CYCLES: Final = 1
DEFAULT_RESTORE: Final = True

MIN_SETTLE: Final = 0
MAX_SETTLE: Final = 600
MIN_WINDOW: Final = 5
MAX_WINDOW: Final = 600
MIN_INTERVAL: Final = 1
MAX_INTERVAL: Final = 60
MIN_CYCLES: Final = 1
MAX_CYCLES: Final = 5

# Entities the probe can switch with homeassistant.turn_on / turn_off.
SUPPORTED_DOMAINS: Final = (
    "switch",
    "light",
    "fan",
    "input_boolean",
    "humidifier",
    "media_player",
    "remote",
    "climate",
)

# Seconds to wait for a device to report the state it was commanded into.
STATE_TIMEOUT: Final = 30
MAX_HISTORY: Final = 50

EVENT_FINISHED: Final = "power_probe_finished"

STATE_IDLE: Final = "idle"
STATE_MEASURING: Final = "measuring"
STATE_FINISHED: Final = "finished"
STATE_FAILED: Final = "failed"
STATE_CANCELLED: Final = "cancelled"
STATES: Final = (
    STATE_IDLE,
    STATE_MEASURING,
    STATE_FINISHED,
    STATE_FAILED,
    STATE_CANCELLED,
)

QUALITY_GOOD: Final = "good"
QUALITY_FAIR: Final = "fair"
QUALITY_POOR: Final = "poor"
QUALITY_INCONCLUSIVE: Final = "inconclusive"
QUALITIES: Final = (QUALITY_GOOD, QUALITY_FAIR, QUALITY_POOR, QUALITY_INCONCLUSIVE)

PANEL_URL_PATH: Final = "power-probe"
PANEL_ELEMENT: Final = "power-probe-panel"
STATIC_URL: Final = "/power_probe_static"
