"""The off, on, off sequence and the arithmetic on its readings.

Nothing here touches Home Assistant. The caller supplies a `Driver` that can
switch the device, read the whole-home meter and sleep, so the sequence runs
the same against a fake in tests and against real entities in the manager.

The method: read the house with the device off, switch it on and read again,
switch it off and read a third time. The device's draw is the "on" reading
minus the average of the two "off" readings around it. The two "off" readings
double as a noise check: if they disagree, something else in the house changed
during the run and the result is flagged instead of trusted.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from .const import (
    QUALITY_FAIR,
    QUALITY_GOOD,
    QUALITY_INCONCLUSIVE,
    QUALITY_POOR,
    STATE_FAILED,
    STATE_IDLE,
    STATE_MEASURING,
)

MIN_SAMPLES = 3
# Distinct meter reports needed in a window before its scatter means anything.
MIN_REPORTS = 3
# Uncertainty as a share of the measured draw.
GOOD_RATIO = 0.10
FAIR_RATIO = 0.25
# Below this many watts the meter's own resolution dominates, so never call
# a result "good" on a ratio alone.
GOOD_FLOOR_W = 0.5
SETTLE_CHUNK_S = 1.0


class ProbeError(Exception):
    """A run cannot start or continue. `code` is the translation key."""

    def __init__(self, code: str, **placeholders: str) -> None:
        super().__init__(code)
        self.code = code
        self.placeholders = placeholders


@dataclass(frozen=True, slots=True)
class MeasureSettings:
    """Timing of one run. All durations are seconds."""

    settle_s: float = 45.0
    window_s: float = 60.0
    interval_s: float = 5.0
    cycles: int = 1

    def step_names(self) -> list[tuple[str, bool]]:
        """Ordered (step, device_on) pairs: off, then (on, off) per cycle."""
        steps = [("off_1", False)]
        for cycle in range(1, self.cycles + 1):
            steps.append((f"on_{cycle}", True))
            steps.append((f"off_{cycle + 1}", False))
        return steps

    def total_seconds(self) -> float:
        """Run time of the timed parts, not counting how long switching takes."""
        return (self.settle_s + self.window_s) * len(self.step_names())

    def as_dict(self) -> dict[str, float | int]:
        return {
            "settle_s": self.settle_s,
            "window_s": self.window_s,
            "interval_s": self.interval_s,
            "cycles": self.cycles,
        }


@dataclass(slots=True)
class Progress:
    """What the UI and the status sensor show while a run is going."""

    state: str = STATE_IDLE
    entity_id: str | None = None
    step: str | None = None
    activity: str | None = None
    percent: int = 0
    seconds_left: int | None = None
    latest_w: float | None = None
    error: str | None = None
    message: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "entity_id": self.entity_id,
            "step": self.step,
            "activity": self.activity,
            "percent": self.percent,
            "seconds_left": self.seconds_left,
            "latest_w": self.latest_w,
            "error": self.error,
            "message": self.message,
        }


@dataclass(slots=True)
class Driver:
    """What a run needs from the outside."""

    set_device: Callable[[bool], Awaitable[None]]
    read_power: Callable[[], float | None]
    sleep: Callable[[float], Awaitable[None]]
    on_progress: Callable[[Progress], None] = lambda _progress: None
    # Identifies the meter's latest report, so that reading the same report
    # twice is not mistaken for two independent readings. None means the
    # driver cannot tell, and every reading counts as new.
    read_update: Callable[[], object | None] = lambda: None


@dataclass(frozen=True, slots=True)
class Window:
    """Readings taken while one step was settled.

    `samples` are every reading taken. `fresh` is the value of each distinct
    meter report among them: sampling every 5 s from a meter that updates every
    16 s reads each report about three times, and only the reports are
    independent. The average uses every sample; the scatter uses the reports.
    """

    step: str
    device_on: bool
    samples: tuple[tuple[float, float], ...]
    fresh: tuple[float, ...] | None = None

    @property
    def values(self) -> list[float]:
        return [watts for _t, watts in self.samples]

    @property
    def reports(self) -> list[float]:
        """One value per distinct meter report."""
        return list(self.fresh) if self.fresh is not None else self.values

    @property
    def mean(self) -> float:
        return statistics.fmean(self.values)

    @property
    def stdev(self) -> float:
        reports = self.reports
        return statistics.stdev(reports) if len(reports) > 1 else 0.0

    @property
    def sem(self) -> float:
        """Standard error of the mean: how well the average is pinned down."""
        return self.stdev / math.sqrt(len(self.reports))

    def as_dict(self) -> dict[str, Any]:
        return {
            "step": self.step,
            "device_on": self.device_on,
            "mean_w": round(self.mean, 2),
            "stdev_w": round(self.stdev, 2),
            "reports": len(self.reports),
            "samples": [[round(t, 1), round(w, 2)] for t, w in self.samples],
        }


@dataclass(frozen=True, slots=True)
class Outcome:
    """The result of one run."""

    power_w: float
    uncertainty_w: float
    quality: str
    limiting: str
    off_start_w: float
    on_w: float
    off_end_w: float
    drift_w: float
    cycle_deltas: tuple[float, ...]
    warnings: tuple[str, ...] = field(default=())

    def as_dict(self) -> dict[str, Any]:
        return {
            "power_w": round(self.power_w, 1),
            "uncertainty_w": round(self.uncertainty_w, 1),
            "quality": self.quality,
            "limiting": self.limiting,
            "off_start_w": round(self.off_start_w, 1),
            "on_w": round(self.on_w, 1),
            "off_end_w": round(self.off_end_w, 1),
            "drift_w": round(self.drift_w, 1),
            "cycle_deltas_w": [round(delta, 1) for delta in self.cycle_deltas],
            "warnings": list(self.warnings),
        }


def summarize(windows: Sequence[Window]) -> Outcome:
    """Turn the readings of a finished run into a device power and a verdict.

    `windows` must be in run order: off, (on, off) per cycle.
    """
    offs = [window for window in windows if not window.device_on]
    ons = [window for window in windows if window.device_on]
    if len(offs) < 2 or not ons or len(offs) != len(ons) + 1:
        raise ValueError("windows must alternate off, on, off")

    cycle_deltas = tuple(
        on.mean - (offs[index].mean + offs[index + 1].mean) / 2
        for index, on in enumerate(ons)
    )
    power = statistics.fmean(cycle_deltas)
    drift = offs[-1].mean - offs[0].mean

    # Three independent ways the answer can be off. The largest one limits
    # how far to trust it, and naming it tells the user what to fix.
    terms = {
        "drift": abs(drift) / 2,
        "scatter": math.sqrt(sum(window.sem**2 for window in windows)),
        "cycles": statistics.stdev(cycle_deltas) if len(cycle_deltas) > 1 else 0.0,
    }
    limiting = max(terms, key=lambda name: terms[name])
    uncertainty = terms[limiting]

    warnings: list[str] = []
    if (
        all(window.stdev == 0 for window in windows)
        and len({round(window.mean, 3) for window in windows}) == 1
    ):
        warnings.append("meter_not_updating")
    if power <= 0:
        warnings.append("power_not_positive")
    # With fewer than three reports in a window the scatter is a guess, so the
    # result cannot be called good however tight it looks.
    few_updates = any(len(window.reports) < MIN_REPORTS for window in windows)
    if few_updates:
        warnings.append("few_meter_updates")

    if power <= 0 or power <= uncertainty:
        quality = QUALITY_INCONCLUSIVE
    elif uncertainty <= max(GOOD_RATIO * power, GOOD_FLOOR_W) and not few_updates:
        quality = QUALITY_GOOD
    elif uncertainty <= FAIR_RATIO * power:
        quality = QUALITY_FAIR
    else:
        quality = QUALITY_POOR

    return Outcome(
        power_w=power,
        uncertainty_w=uncertainty,
        quality=quality,
        limiting=limiting,
        off_start_w=offs[0].mean,
        on_w=statistics.fmean(window.mean for window in ons),
        off_end_w=offs[-1].mean,
        drift_w=drift,
        cycle_deltas=cycle_deltas,
        warnings=tuple(warnings),
    )


class _Clock:
    """Run time as the sum of the sleeps, so progress needs no real clock."""

    def __init__(self, settings: MeasureSettings, driver: Driver, entity_id: str):
        self._settings = settings
        self._driver = driver
        self._total = settings.total_seconds()
        self._elapsed = 0.0
        self.progress = Progress(state=STATE_MEASURING, entity_id=entity_id)

    @property
    def elapsed(self) -> float:
        return self._elapsed

    def report(self, step: str, activity: str) -> None:
        progress = self.progress
        progress.step = step
        progress.activity = activity
        progress.latest_w = self._driver.read_power()
        left = max(self._total - self._elapsed, 0.0)
        progress.seconds_left = math.ceil(left)
        if self._total > 0:
            progress.percent = min(99, int(100 * self._elapsed / self._total))
        self._driver.on_progress(progress)

    async def sleep(self, seconds: float, step: str, activity: str) -> None:
        await self._driver.sleep(seconds)
        self._elapsed += seconds
        self.report(step, activity)


async def run_sequence(
    settings: MeasureSettings, driver: Driver, entity_id: str
) -> list[Window]:
    """Run off, (on, off) per cycle, and return the readings of each step.

    Raises ProbeError when the meter gives too few readings to trust a step.
    Cancelling the task cancels the sequence; restoring the device is the
    caller's job.
    """
    clock = _Clock(settings, driver, entity_id)
    windows: list[Window] = []
    for step, device_on in settings.step_names():
        clock.report(step, "switching")
        await driver.set_device(device_on)

        remaining = settings.settle_s
        while remaining > 0:
            chunk = min(SETTLE_CHUNK_S, remaining)
            await clock.sleep(chunk, step, "settling")
            remaining -= chunk

        samples: list[tuple[float, float]] = []
        fresh: list[float] = []
        last_update: object = None
        taken = 0.0
        while True:
            watts = driver.read_power()
            if watts is not None:
                samples.append((taken, watts))
                update = driver.read_update()
                if update is None or update != last_update:
                    fresh.append(watts)
                last_update = update
            clock.report(step, "sampling")
            if taken >= settings.window_s:
                break
            pause = min(settings.interval_s, settings.window_s - taken)
            await clock.sleep(pause, step, "sampling")
            taken += pause
        if len(samples) < MIN_SAMPLES:
            raise ProbeError("meter_unavailable_during_run")
        windows.append(Window(step, device_on, tuple(samples), tuple(fresh)))
    return windows


def failed_progress(entity_id: str | None, code: str) -> Progress:
    """Progress record for a run that stopped with an error."""
    return Progress(state=STATE_FAILED, entity_id=entity_id, error=code)
