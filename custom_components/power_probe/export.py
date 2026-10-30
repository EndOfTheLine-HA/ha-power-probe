"""Turn a measured wattage into something Powercalc accepts."""

from __future__ import annotations


def format_watts(power_w: float) -> str:
    """Watts to one decimal, without a trailing .0."""
    return f"{round(power_w, 1):g}"


def powercalc_yaml(entity_id: str, power_w: float) -> str:
    """A YAML snippet for configuration.yaml using Powercalc's fixed strategy.

    Powercalc treats the fixed power as the draw while the entity is on. The
    same value can be typed into Powercalc's own UI: add a virtual power
    sensor, pick the entity, choose the fixed strategy and enter the watts.
    """
    return (
        "powercalc:\n"
        "  sensors:\n"
        f"    - entity_id: {entity_id}\n"
        "      fixed:\n"
        f"        power: {format_watts(power_w)}\n"
    )
