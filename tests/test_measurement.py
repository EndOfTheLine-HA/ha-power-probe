"""The off, on, off sequence and its arithmetic, with no Home Assistant."""

from __future__ import annotations

import pytest

from custom_components.power_probe.export import format_watts, powercalc_yaml
from custom_components.power_probe.measurement import (
    MeasureSettings,
    ProbeError,
    Window,
    run_sequence,
    summarize,
)
from tests.conftest import FakeDriver

QUICK = MeasureSettings(settle_s=2, window_s=6, interval_s=2, cycles=1)


def test_step_order_for_one_and_two_cycles():
    assert QUICK.step_names() == [("off_1", False), ("on_1", True), ("off_2", False)]
    two = MeasureSettings(cycles=2).step_names()
    assert [name for name, _ in two] == ["off_1", "on_1", "off_2", "on_2", "off_3"]
    assert [on for _, on in two] == [False, True, False, True, False]


def test_total_seconds_counts_every_step():
    assert QUICK.total_seconds() == (2 + 6) * 3


async def test_run_matches_the_requested_sequence():
    fake = FakeDriver(base=200, device=60)
    windows = await run_sequence(QUICK, fake.driver(), "switch.x")
    assert fake.switches == [False, True, False]
    assert [w.step for w in windows] == ["off_1", "on_1", "off_2"]
    assert [w.device_on for w in windows] == [False, True, False]
    # 6 s window read every 2 s: readings at 0, 2, 4 and 6 s.
    assert all(len(w.samples) == 4 for w in windows)
    outcome = summarize(windows)
    assert outcome.power_w == pytest.approx(60)
    assert outcome.off_start_w == pytest.approx(200)
    assert outcome.on_w == pytest.approx(260)
    assert outcome.off_end_w == pytest.approx(200)
    assert outcome.quality == "good"
    assert outcome.warnings == ()


async def test_progress_reports_each_step_and_never_hits_100():
    fake = FakeDriver()
    await run_sequence(QUICK, fake.driver(), "switch.x")
    steps = []
    for item in fake.progress:
        if item["step"] not in steps:
            steps.append(item["step"])
    assert steps == ["off_1", "on_1", "off_2"]
    percents = [item["percent"] for item in fake.progress]
    assert percents == sorted(percents)
    assert max(percents) < 100
    assert {item["activity"] for item in fake.progress} == {
        "switching",
        "settling",
        "sampling",
    }
    assert all(item["state"] == "measuring" for item in fake.progress)


async def test_two_cycles_average_both():
    fake = FakeDriver(base=300, device=100)
    settings = MeasureSettings(settle_s=1, window_s=4, interval_s=2, cycles=2)
    windows = await run_sequence(settings, fake.driver(), "switch.x")
    assert len(windows) == 5
    outcome = summarize(windows)
    assert outcome.power_w == pytest.approx(100)
    assert len(outcome.cycle_deltas) == 2


async def test_steady_drift_is_flagged_not_trusted():
    """The house climbs 1 W a second: the off readings disagree widely."""
    fake = FakeDriver(base=200, device=6, drift_per_s=1.0)
    windows = await run_sequence(QUICK, fake.driver(), "switch.x")
    outcome = summarize(windows)
    assert outcome.drift_w == pytest.approx(16)
    assert outcome.limiting == "drift"
    assert outcome.quality == "inconclusive"


async def test_cycles_that_disagree_limit_the_result():
    fake = FakeDriver(base=200, device=30)
    settings = MeasureSettings(settle_s=0, window_s=2, interval_s=1, cycles=2)
    real_set_device = fake.set_device

    # The device really draws 30 W in the first cycle and 70 W in the second.
    async def set_device(on: bool) -> None:
        await real_set_device(on)
        if on:
            fake.device = 30.0 if fake.switches.count(True) == 1 else 70.0

    fake.set_device = set_device
    outcome = summarize(await run_sequence(settings, fake.driver(), "switch.x"))
    assert outcome.cycle_deltas == (pytest.approx(30), pytest.approx(70))
    assert outcome.limiting == "cycles"
    assert outcome.power_w == pytest.approx(50)
    assert outcome.quality == "poor"


async def test_noisy_meter_widens_the_uncertainty():
    quiet = FakeDriver(base=200, device=60)
    noisy = FakeDriver(base=200, device=60)
    noisy.noise = [-8.0, 8.0, -3.0, 3.0, 0.0]
    quiet_out = summarize(await run_sequence(QUICK, quiet.driver(), "x"))
    noisy_out = summarize(await run_sequence(QUICK, noisy.driver(), "x"))
    assert noisy_out.uncertainty_w > quiet_out.uncertainty_w


async def test_flat_meter_gets_a_warning():
    fake = FakeDriver(base=200, device=0)
    outcome = summarize(await run_sequence(QUICK, fake.driver(), "x"))
    assert "meter_not_updating" in outcome.warnings
    assert outcome.quality == "inconclusive"


async def test_device_that_adds_no_load_is_inconclusive():
    fake = FakeDriver(base=200, device=-5)
    outcome = summarize(await run_sequence(QUICK, fake.driver(), "x"))
    assert outcome.power_w == pytest.approx(-5)
    assert "power_not_positive" in outcome.warnings
    assert outcome.quality == "inconclusive"


async def test_too_few_readings_raise_a_translated_error():
    fake = FakeDriver()
    fake.blank = True
    with pytest.raises(ProbeError) as raised:
        await run_sequence(QUICK, fake.driver(), "x")
    assert raised.value.code == "meter_unavailable_during_run"


def test_summarize_rejects_a_sequence_that_does_not_alternate():
    window = Window("off_1", False, ((0.0, 1.0), (1.0, 1.0), (2.0, 1.0)))
    with pytest.raises(ValueError):
        summarize([window, window])


def test_window_statistics():
    window = Window("off_1", False, ((0.0, 10.0), (1.0, 12.0), (2.0, 14.0)))
    assert window.mean == pytest.approx(12)
    assert window.stdev == pytest.approx(2)
    assert window.sem == pytest.approx(2 / 3**0.5)
    assert window.as_dict()["samples"][0] == [0.0, 10.0]


def test_powercalc_snippet_and_rounding():
    assert format_watts(12.0) == "12"
    assert format_watts(12.34) == "12.3"
    assert format_watts(0.05) == "0.1"
    assert powercalc_yaml("switch.heater", 1500.04) == (
        "powercalc:\n"
        "  sensors:\n"
        "    - entity_id: switch.heater\n"
        "      fixed:\n"
        "        power: 1500\n"
    )


NOISE = [-9.0, 7.0, -4.0, 10.0, -6.0, 3.0, -8.0, 5.0]


def slow_meter(ids: bool = True) -> FakeDriver:
    """A meter that reports every 10 s, with noise on each report."""
    fake = FakeDriver(base=500, device=100)
    fake.noise = NOISE
    fake.update_every = 10
    fake.ids = ids
    return fake


async def test_reading_one_report_twice_does_not_shrink_the_scatter():
    """Sampling faster than the meter updates must not look like more data."""
    every_2s = MeasureSettings(settle_s=20, window_s=60, interval_s=2)
    every_10s = MeasureSettings(settle_s=20, window_s=60, interval_s=10)
    oversampled = await run_sequence(every_2s, slow_meter().driver(), "x")
    once_each = await run_sequence(every_10s, slow_meter().driver(), "x")
    blind = await run_sequence(every_2s, slow_meter(ids=False).driver(), "x")

    # Same seven reports in each window, however often they were read.
    assert [len(w.reports) for w in oversampled] == [7, 7, 7]
    assert [len(w.reports) for w in once_each] == [7, 7, 7]
    assert len(oversampled[0].samples) > len(once_each[0].samples)
    for a, b in zip(oversampled, once_each, strict=True):
        assert a.stdev == pytest.approx(b.stdev)
        assert a.sem == pytest.approx(b.sem)
    # A driver that cannot tell reports apart counts every read and looks
    # more certain than the meter justifies.
    for honest, naive in zip(oversampled, blind, strict=True):
        assert naive.sem < honest.sem


async def test_too_few_meter_reports_cap_the_quality():
    """One report per window says nothing about scatter, so never 'good'."""
    fake = FakeDriver(base=500, device=60)
    fake.update_every = 100
    settings = MeasureSettings(settle_s=10, window_s=20, interval_s=2)
    windows = await run_sequence(settings, fake.driver(), "x")
    assert [len(w.reports) for w in windows] == [1, 1, 1]
    outcome = summarize(windows)
    assert outcome.power_w == pytest.approx(60)
    assert outcome.uncertainty_w == 0
    assert "few_meter_updates" in outcome.warnings
    assert outcome.quality == "fair"


async def test_enough_meter_reports_keep_a_good_result_good():
    fake = FakeDriver(base=500, device=300)
    fake.update_every = 10
    settings = MeasureSettings(settle_s=20, window_s=60, interval_s=5)
    outcome = summarize(await run_sequence(settings, fake.driver(), "x"))
    assert "few_meter_updates" not in outcome.warnings
    assert outcome.quality == "good"
