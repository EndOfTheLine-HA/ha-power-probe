# Power Probe

Find out how much power a device really uses, using the whole-home energy meter you already have. No smart plug with power monitoring needed.

Power Probe switches a device off, reads your whole-home power sensor, switches the device on, reads again, then switches it off and reads a last time. The difference is the device's draw. The result is ready to use with [Powercalc](https://github.com/bramstroker/homeassistant-powercalc) or any other tool that wants a wattage.

It works with any power sensor in watts or kilowatts, for example a Refoss, Emporia Vue, Sense, Shelly EM or IoTaWatt meter.

## Why this exists

Powercalc ships a measure tool, but it expects a power meter on the device itself (a monitoring plug, for example). Many devices cannot sit behind a plug: lights on a dimmer, a fan on a wall switch, a ceiling heater. If you have a whole-home meter, you can measure them anyway by watching the house total change.

## How it measures

1. Switch the device off, wait for the meter to settle, and average the readings over a window. This is the first baseline.
2. Switch the device on, settle, and average again.
3. Switch the device off again, settle, and average a third time. This is the final baseline.

The device's power is the "on" average minus the mean of the two "off" averages around it. Using both off readings cancels a house load that is slowly rising or falling.

The two off readings also tell you how far to trust the answer. If they disagree, something else changed in the house during the run (a fridge compressor, a heat pump, the oven). Power Probe reports an uncertainty and a quality rating, and says which of three things limited it:

| Limit | Meaning | Fix |
| --- | --- | --- |
| drift | The two off readings disagree | Run again when the house is quiet, or use more cycles |
| scatter | The meter is noisy compared with the device's draw | Longer reading window, or more cycles |
| cycles | Repeated cycles disagree with each other | Longer settle time |

Quality is **good** when the uncertainty is under 10% of the result (or half a watt), **fair** under 25%, **poor** above that, and **inconclusive** when the uncertainty is as large as the result itself or the house used no more power with the device on.

## Install

Until Power Probe is in the HACS default list, add it as a custom repository:

1. In HACS, open the three-dot menu, choose **Custom repositories**, and add `https://github.com/EndOfTheLine-HA/ha-power-probe` as an **Integration**.
2. Download **Power Probe** and restart Home Assistant.
3. Go to **Settings, Devices & services, Add integration** and pick **Power Probe**.

Manual install: copy `custom_components/power_probe` into your Home Assistant `custom_components` folder and restart.

Requires Home Assistant 2026.10.2 or newer.

## Set up

When you add the integration you choose:

- **Whole-home power sensor.** The default meter. You can pick another for any single run.
- **How fast the sensor updates.** This sets the timing. The settle time has to outlast the sensor's update interval, or the first readings of each step still show the previous state.

  | Profile | Settle | Window | Reading every | Use for |
  | --- | --- | --- | --- | --- |
  | Fast | 15 s | 20 s | 2 s | Sensors that change every few seconds |
  | Medium | 45 s | 60 s | 5 s | Sensors that change every 10 to 30 seconds |
  | Slow | 120 s | 150 s | 5 s | Sensors that update about once a minute |
  | Custom | you choose | you choose | you choose | Anything else |

  Not sure how often your sensor updates? Open its history graph and look at the spacing of the steps. Local meters are usually faster than cloud-polled ones.

  Each reading window needs at least **three real updates** from the meter. Power Probe counts distinct meter reports, not how often it looks, so reading a slow meter every 5 seconds does not make it look more certain. If any window has fewer than three, the result carries a "few meter updates" warning and cannot be rated Good. A sensor that reports less often than about once a minute (a one-minute average that publishes every two minutes, say) fits none of the presets: use Custom with a window at least three times its update interval and a settle time longer than that interval. Runs get long, so a faster meter is usually the better answer.
- **Cycles.** 1 runs off, on, off (the three readings above). 2 to 5 repeat on and off and average the results, which helps when other loads are switching in the house. Each extra cycle adds one on step and one off step.
- **Put the device back how it was.** After the final off reading, turn the device back on if it was on when the run started.

All of these can be changed later in the integration's options.

A run takes `(settle + window) x (2 x cycles + 1)` seconds. With Medium timing and one cycle that is about five and a half minutes.

## The sidebar panel

Admins get a **Power Probe** entry in the sidebar.

1. Pick the whole-home sensor. The current reading is shown so you can see it is live.
2. Filter and pick the device to test.
3. Open **Timing** if you want to change the profile, seconds, cycles or restore behaviour for this run.
4. Press **Start measurement**. The panel shows each step, the live house reading and the time left, and has a Cancel button.
5. When it finishes you get the device's power, the uncertainty, a quality rating, the three house readings, the drift, and a ready-made Powercalc snippet with a copy button. Earlier results are listed below and can be reopened or deleted.

## Using it from automations and scripts

Start a run from a script, an automation or Developer tools:

```yaml
action: power_probe.start_measurement
data:
  entity_id: switch.coffee_maker
  # Optional overrides for this run:
  power_entity: sensor.whole_home_power
  settle_time: 30
  sample_window: 40
  sample_interval: 2
  cycles: 1
  restore_state: true
```

Without a response variable the action returns at once and the run continues in the background. With one, it waits and hands you the result:

```yaml
- action: power_probe.start_measurement
  data:
    entity_id: switch.coffee_maker
  response_variable: probe
- action: persistent_notification.create
  data:
    title: Coffee maker
    message: >-
      {{ probe.power_w }} W, {{ probe.quality }}
```

If the script is stopped while it waits, the run is cancelled and the device is put back.

`power_probe.cancel_measurement` stops a run in progress and puts the device back.

When a run ends, Power Probe fires a `power_probe_finished` event with `entity_id`, `success`, and either `result` or `error`.

### Entities

| Entity | What it shows |
| --- | --- |
| `sensor.power_probe_status` | idle, measuring, finished, failed or cancelled, with the step, activity, percent, seconds left and latest house reading as attributes |
| `sensor.power_probe_last_measured_power` | The last finished result in watts, with quality, uncertainty, the three house readings, drift and the Powercalc snippet as attributes |

Results are also stored (the latest 50) and survive restarts.

### Result fields

`power_w`, `uncertainty_w`, `quality`, `limiting`, `off_start_w`, `on_w`, `off_end_w`, `drift_w`, `cycle_deltas_w`, `warnings`, `windows` (every reading of every step, with its time), `settings`, `powercalc_yaml`, plus the device, meter and timestamps.

## Using the result with Powercalc

Power Probe gives you a number for a device Powercalc can then track. Add it to `configuration.yaml`:

```yaml
powercalc:
  sensors:
    - entity_id: switch.coffee_maker
      fixed:
        power: 1180
```

Or use Powercalc's own UI: add a virtual power sensor, pick the device, choose the **fixed** strategy and enter the watts.

Two notes:

- Power Probe measures the extra draw when the device is on compared with off. If the device is cut from the mains when it is "off" (a smart plug, or a switch that opens the circuit), that is its full draw. If it keeps drawing a little when off (a smart bulb, a TV on standby), the real on-power is the measured value plus that standby draw. Add `standby_power` to the Powercalc sensor if you want it counted.
- This measures one operating point. For a dimmable light or a variable-speed fan the draw changes with the setting, so measure the setting you care about, or use Powercalc's linear strategy with two measurements.

## Getting a good measurement

- Run it when the house is quiet. Heat pumps, ovens, EV chargers, well pumps and dryers swamp small loads.
- Bigger loads measure better. A 5 W device on a meter with a few watts of noise is not going to give a clean answer. The quality rating will say so.
- On a net meter in a house with solar, cloud passing over the panels counts as house load changing. Run it at night or on a steady day.
- Make sure the sensor really is the whole house, not one circuit the device is not on.
- If the quality is not good, run again with more cycles before changing anything else. More cycles average out random swings. They do not help if the house load simply keeps rising.

### How accurate is it?

One short run is good to roughly **plus or minus 60 W in a house with unmetered loads that cycle**, and the uncertainty it reports is meant to say so. That suits loads of about 500 W and up. For anything smaller, use several cycles and treat the number as an estimate.

Two checks in one real house, with a local meter that reports about every 16 seconds, one cycle, about 4 to 5 minutes each:

| Device | Reference | Power Probe | Rating |
| --- | --- | --- | --- |
| A floor fan | 146.5 W, from a plug-in power monitor | 183.9 W, plus or minus 70 W | Poor |
| Four 40 W incandescent bulbs on a dimmer | about 160 W, from the bulb rating | 95.5 W, plus or minus 54 W | Poor |

Both were within about 1.2 times their stated uncertainty of the reference, in opposite directions. The house load wandered by 100 W or more during each run, which is what the Poor rating reported. Treat a Poor result as "roughly this, and no better than that" rather than a measurement.

## Safety

Power Probe turns the device off and on. Do not use it on anything that must stay running: a fridge, a freezer, medical equipment, a sump pump, or anything life-safety related. A run keeps the device off for a few minutes in total, and switches it on for a couple of minutes at a time. If a run fails or is cancelled, the device is put back the way it was (or left off if you turned the restore option off).

If Home Assistant restarts or loses power in the middle of a run, Power Probe has already written the run down before it switched anything. On the next start, once everything is up, it puts the device back the way it should be and fires `power_probe_finished` with the error `interrupted`. If the device cannot be reached it tries again at the next start. Until Home Assistant is back, a device that was on at that moment stays on, so stay nearby when you test a heater or anything that gets hot.

Only admins can open the panel. Any user who can call actions can call `power_probe.start_measurement`, the same way they can already call `switch.turn_off`.

## Supported devices

Anything Home Assistant can turn on and off with `homeassistant.turn_on` and `homeassistant.turn_off` in these domains: switch, light, fan, input_boolean, humidifier, media_player, remote, climate. A light comes on at whatever brightness it turns on to by default, so the result is for that brightness.

## Troubleshooting

| Message or symptom | What to do |
| --- | --- |
| "A measurement is already running" | Cancel it from the panel, or call `power_probe.cancel_measurement` |
| "reports in ..., which is not a power unit" | Pick a sensor in W or kW, not an energy sensor in kWh |
| "did not turn on/off within 30 seconds" | The device is not responding to Home Assistant. Check it works from the dashboard |
| "stopped giving readings during the run" | The meter went unavailable. Check its connection and run again |
| Result is inconclusive with "meter never changed" | The sensor is not updating, or it is not measuring the whole house |
| Result is much lower than expected | Settle time is probably shorter than the sensor's update interval. Use a slower profile |
| Result carries "few meter updates" | The sensor reported fewer than three times in at least one window. Use a longer window or a slower profile |

## Development

```bash
uv venv --python 3.14
uv pip install homeassistant==2026.10.2 pytest pytest-asyncio ruff
.venv/Scripts/python -m pytest
.venv/Scripts/python -m ruff check .
```

The measurement logic in `custom_components/power_probe/measurement.py` has no Home Assistant dependency and is tested against a simulated house. The integration tests run real config flows, actions and sensors against a fake meter whose reading follows a fake device, and replace the clock so a ten minute run takes milliseconds.

Tested on one real house with a Refoss EM16P local meter (see how accurate it was above) and on simulated meters. Not tried on Sense or Shelly meters. An Emporia Utility Connect sensor in that house reported only about every two minutes, which is too slow for a normal run.

## License

MIT
