# Changelog

## 0.1.0 (unreleased)

First version.

- Measure a device's power with any whole-home power sensor by switching it off, on and off again and comparing the readings.
- Uncertainty and quality rating from how far the two off readings drift apart, the meter's own scatter, and the spread between repeated cycles.
- Timing presets for fast, medium and slow sensors, or custom seconds. One to five cycles.
- Sidebar panel for admins with live progress, cancel, results, history and a Powercalc snippet.
- `power_probe.start_measurement` (optionally returns the result) and `power_probe.cancel_measurement` actions, a `power_probe_finished` event, a status sensor and a last-result sensor.
- Device restored to its starting state after a finished, failed or cancelled run.
- Last 50 results kept across restarts.
- A run is written down before the device is switched. After a Home Assistant restart or power cut, the device is put back once Home Assistant has started, and `power_probe_finished` fires with the error `interrupted`.
- Uncertainty counts distinct meter reports, not readings, and a window with fewer than three reports adds a warning and cannot be rated Good.
