/* Power Probe sidebar panel. No build step: one custom element, no libraries. */

const ERRORS = {
  busy: "A measurement is already running.",
  no_meter: "Choose a whole-home power sensor first.",
  device_not_supported: "Power Probe cannot switch that kind of entity.",
  device_unavailable: "That device is not available right now.",
  meter_unavailable: "The whole-home sensor has no usable reading right now.",
  meter_not_power: "That sensor does not report in watts or kilowatts.",
  interval_longer_than_window:
    "The time between readings cannot be longer than the reading window.",
  device_did_not_change: "The device did not change state in 30 seconds.",
  meter_unavailable_during_run:
    "The whole-home sensor stopped giving readings during the run.",
  command_failed: "Home Assistant could not switch the device. Check the log.",
  interrupted: "A restart interrupted this run. The device was put back the way it was.",
  unknown: "The measurement failed. Check the log.",
};

const ACTIVITY = {
  switching: "Switching the device",
  settling: "Letting the meter settle",
  sampling: "Reading the meter",
};

const WHY = {
  drift:
    "Other loads in the house changed while the test ran, so the two off readings disagree. Run it again when the house is quiet, or raise the number of cycles.",
  scatter:
    "The meter reading is noisy compared with this device's draw. Use a longer reading window or more cycles.",
  cycles:
    "The repeated cycles disagreed with each other. Try a longer settle time.",
};

const WARNINGS = {
  meter_not_updating:
    "The meter reading never changed during the run. Check that the sensor updates and measures the whole house.",
  power_not_positive:
    "The house did not use more power with the device on. Check it is the right entity, and that nothing else switched off at the same time.",
  few_meter_updates:
    "The meter reported fewer than three times in at least one reading window, so the uncertainty is only a rough guide. Use a longer reading window or a slower timing profile.",
};

const QUALITY_TEXT = {
  good: "Good",
  fair: "Fair",
  poor: "Poor",
  inconclusive: "Inconclusive",
};

const STYLE = `
  :host { display: block; background: var(--primary-background-color); color: var(--primary-text-color); min-height: 100%; }
  .wrap { max-width: 760px; margin: 0 auto; padding: 16px; box-sizing: border-box; }
  header { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }
  ha-menu-button { flex: none; }
  h1 { font-size: 24px; font-weight: 400; margin: 0; }
  h2 { font-size: 16px; font-weight: 500; margin: 0 0 12px; }
  p { margin: 0 0 12px; line-height: 1.45; }
  .muted { color: var(--secondary-text-color); font-size: 14px; }
  .card { background: var(--card-background-color); border-radius: var(--ha-card-border-radius, 12px); border: 1px solid var(--divider-color); padding: 16px; margin-bottom: 16px; }
  label { display: block; font-size: 14px; font-weight: 500; margin: 12px 0 4px; }
  select, input { width: 100%; box-sizing: border-box; padding: 8px; font: inherit; color: var(--primary-text-color); background: var(--secondary-background-color, transparent); border: 1px solid var(--divider-color); border-radius: 8px; }
  select[size] { padding: 4px; }
  .row { display: flex; gap: 12px; flex-wrap: wrap; }
  .row > div { flex: 1 1 140px; }
  .check { display: flex; align-items: center; gap: 8px; margin-top: 12px; font-size: 14px; }
  .check input { width: auto; }
  details { margin-top: 12px; }
  summary { cursor: pointer; font-size: 14px; font-weight: 500; }
  button { font: inherit; border: 0; border-radius: 8px; padding: 10px 18px; cursor: pointer; background: var(--primary-color); color: var(--text-primary-color, #fff); }
  button.secondary { background: transparent; color: var(--primary-color); border: 1px solid var(--divider-color); }
  button.danger { background: var(--error-color, #db4437); }
  button:disabled { opacity: 0.5; cursor: default; }
  .actions { display: flex; gap: 8px; margin-top: 16px; flex-wrap: wrap; }
  .error { color: var(--error-color, #db4437); margin-top: 12px; }
  .steps { list-style: none; padding: 0; margin: 0 0 12px; }
  .steps li { display: flex; align-items: center; gap: 8px; padding: 4px 0; color: var(--secondary-text-color); }
  .steps li.current { color: var(--primary-text-color); font-weight: 500; }
  .steps li.done { color: var(--primary-text-color); }
  .dot { width: 10px; height: 10px; border-radius: 50%; border: 2px solid var(--divider-color); flex: none; }
  .current .dot { border-color: var(--primary-color); background: var(--primary-color); }
  .done .dot { border-color: var(--success-color, #0f9d58); background: var(--success-color, #0f9d58); }
  .bar { height: 8px; border-radius: 4px; background: var(--divider-color); overflow: hidden; }
  .bar > div { height: 100%; background: var(--primary-color); width: 0; transition: width 0.4s; }
  .big { font-size: 40px; font-weight: 300; line-height: 1.1; }
  .big small { font-size: 18px; color: var(--secondary-text-color); }
  .badge { display: inline-block; padding: 2px 10px; border-radius: 999px; font-size: 13px; font-weight: 500; color: #fff; margin-left: 8px; vertical-align: middle; }
  .badge.good { background: var(--success-color, #0f9d58); }
  .badge.fair { background: var(--warning-color, #f4b400); color: #000; }
  .badge.poor { background: var(--warning-color, #f4b400); color: #000; }
  .badge.inconclusive { background: var(--error-color, #db4437); }
  .stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(130px, 1fr)); gap: 8px; margin: 12px 0; }
  .stat { background: var(--secondary-background-color, transparent); border-radius: 8px; padding: 8px 12px; }
  .stat b { display: block; font-size: 18px; font-weight: 500; }
  pre { background: var(--secondary-background-color, #f5f5f5); border-radius: 8px; padding: 12px; overflow-x: auto; margin: 8px 0; font-size: 13px; }
  .hist { display: flex; align-items: center; gap: 8px; padding: 8px 0; border-top: 1px solid var(--divider-color); }
  .hist:first-of-type { border-top: 0; }
  .hist .grow { flex: 1; min-width: 0; cursor: pointer; }
  .hist .grow span { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .hist button { padding: 4px 10px; }
  [hidden] { display: none !important; }
`;

const TEMPLATE = `
  <style>${STYLE}</style>
  <div class="wrap">
    <header><ha-menu-button id="menu"></ha-menu-button><h1>Power Probe</h1></header>
    <p class="muted">Find out how much power a device uses with the whole-home meter you already have. Power Probe switches the device off, reads the house, switches it on, reads again, then switches it off and reads a last time.</p>

    <div class="card" id="setup">
      <h2>New measurement</h2>
      <label for="meter">Whole-home power sensor</label>
      <select id="meter"></select>
      <div class="muted" id="meterNow"></div>

      <label for="filter">Device to test</label>
      <input id="filter" type="search" placeholder="Filter by name or entity id">
      <select id="device" size="6"></select>

      <details id="timing">
        <summary>Timing</summary>
        <label for="profile">How fast does the sensor update?</label>
        <select id="profile">
          <option value="fast">Fast (every few seconds)</option>
          <option value="medium">Medium (every 10 to 30 seconds)</option>
          <option value="slow">Slow (about once a minute)</option>
          <option value="custom">Custom</option>
        </select>
        <div class="row">
          <div><label for="settle">Settle (s)</label><input id="settle" type="number" min="0" max="600"></div>
          <div><label for="window">Window (s)</label><input id="window" type="number" min="5" max="600"></div>
          <div><label for="interval">Every (s)</label><input id="interval" type="number" min="1" max="60"></div>
          <div><label for="cycles">Cycles</label><input id="cycles" type="number" min="1" max="5"></div>
        </div>
        <label class="check"><input id="restore" type="checkbox"> Put the device back how it was afterwards</label>
      </details>

      <p class="muted" id="plan" style="margin-top:12px"></p>
      <p class="muted">Do not use this on anything that must stay on, such as a fridge, freezer or medical device. Avoid starting other big loads during the run.</p>
      <div class="error" id="startError" hidden></div>
      <div class="actions"><button id="start">Start measurement</button></div>
    </div>

    <div class="card" id="progress" hidden>
      <h2 id="progressTitle">Measuring</h2>
      <ul class="steps" id="steps"></ul>
      <div class="bar"><div id="bar"></div></div>
      <p class="muted" id="progressText" style="margin-top:8px"></p>
      <div class="actions"><button class="danger" id="cancel">Cancel</button></div>
    </div>

    <div class="card" id="result" hidden></div>

    <div class="card" id="historyCard" hidden>
      <h2>Previous results</h2>
      <div id="history"></div>
    </div>
  </div>
`;

function el(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  Object.assign(node, props);
  for (const child of children) {
    node.append(child);
  }
  return node;
}

function watts(value) {
  return `${Number(value).toFixed(1)} W`;
}

function stepLabel(step, total) {
  const [kind, num] = step.split("_");
  if (kind === "on") return total > 3 ? `On (cycle ${num})` : "On";
  if (Number(num) === 1) return "Off: baseline";
  if (Number(num) === (total - 1) / 2 + 1) return "Off: final";
  return "Off";
}

class PowerProbePanel extends HTMLElement {
  constructor() {
    super();
    this._root = this.attachShadow({ mode: "open" });
    this._root.innerHTML = TEMPLATE;
    this._hass = null;
    this._info = null;
    this._history = [];
    this._progress = null;
    this._shown = null;
    this._unsub = null;
    this._lastPick = 0;
    this._pickKey = "";
    this._loading = false;
    this._wire();
  }

  $(id) {
    return this._root.getElementById(id);
  }

  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;
    this.$("menu").hass = hass;
    if (first) this._load();
    this._updateMeterNow();
    const now = Date.now();
    if (this._info && now - this._lastPick > 5000) {
      this._lastPick = now;
      this._fillPickers();
    }
  }

  // Home Assistant hides the sidebar on narrow screens; a custom panel has to
  // bring its own button to open it again.
  set narrow(value) {
    this.$("menu").narrow = value;
  }
  set route(_value) {}
  set panel(_value) {}

  connectedCallback() {
    if (this._hass && !this._unsub) this._subscribe();
  }

  disconnectedCallback() {
    if (this._unsub) {
      this._unsub();
      this._unsub = null;
    }
  }

  async _load() {
    if (this._loading) return;
    this._loading = true;
    try {
      this._info = await this._hass.callWS({ type: "power_probe/info" });
    } catch (err) {
      this.$("startError").textContent =
        "Power Probe is not set up. Add it under Settings, Devices and services.";
      this.$("startError").hidden = false;
      this.$("start").disabled = true;
      this._loading = false;
      return;
    }
    this._history = this._info.history;
    this._progress = this._info.progress;
    this._applySettings(this._info.settings, this._info.restore_state);
    this._fillPickers();
    this._renderHistory();
    this._renderProgress();
    await this._subscribe();
    this._loading = false;
  }

  async _subscribe() {
    if (this._unsub || !this._hass) return;
    this._unsub = await this._hass.connection.subscribeMessage(
      (msg) => {
        if (msg.kind === "progress") {
          const wasRunning = this._progress?.state === "measuring";
          this._progress = msg.progress;
          this._renderProgress();
          if (wasRunning && msg.progress.state === "failed") this._showFailure();
          if (wasRunning && msg.progress.state === "cancelled") this._awaiting = false;
        } else if (msg.kind === "history") {
          const before = this._history[0]?.id;
          this._history = msg.history;
          this._renderHistory();
          if (this._history[0] && this._history[0].id !== before && this._awaiting) {
            this._awaiting = false;
            this._showResult(this._history[0]);
          }
        }
      },
      { type: "power_probe/subscribe" },
    );
  }

  _wire() {
    this.$("start").addEventListener("click", () => this._start());
    this.$("cancel").addEventListener("click", () =>
      this._hass.callWS({ type: "power_probe/cancel" }),
    );
    this.$("filter").addEventListener("input", () => this._fillDevices());
    for (const id of ["device", "meter", "settle", "window", "cycles", "interval"]) {
      this.$(id).addEventListener("change", () => this._updatePlan());
    }
    this.$("meter").addEventListener("change", () => this._updateMeterNow());
    this.$("profile").addEventListener("change", () => {
      const preset = this._info?.profiles[this.$("profile").value];
      if (preset) {
        this.$("settle").value = preset.settle_s;
        this.$("window").value = preset.window_s;
        this.$("interval").value = preset.interval_s;
      }
      this._updatePlan();
    });
    for (const id of ["settle", "window", "interval"]) {
      this.$(id).addEventListener("input", () => {
        this.$("profile").value = "custom";
      });
    }
  }

  _applySettings(settings, restore) {
    this.$("settle").value = settings.settle_s;
    this.$("window").value = settings.window_s;
    this.$("interval").value = settings.interval_s;
    this.$("cycles").value = settings.cycles;
    this.$("restore").checked = restore;
    const match = Object.entries(this._info.profiles).find(
      ([, p]) =>
        p.settle_s === settings.settle_s &&
        p.window_s === settings.window_s &&
        p.interval_s === settings.interval_s,
    );
    this.$("profile").value = match ? match[0] : "custom";
    this._updatePlan();
  }

  _candidates() {
    const states = Object.values(this._hass.states);
    const domains = new Set(this._info.supported_domains);
    const meters = [];
    const devices = [];
    for (const s of states) {
      const domain = s.entity_id.split(".")[0];
      const name = s.attributes.friendly_name || s.entity_id;
      if (domain === "sensor" && s.attributes.device_class === "power") {
        meters.push({ id: s.entity_id, name });
      } else if (domains.has(domain)) {
        devices.push({ id: s.entity_id, name });
      }
    }
    const byName = (a, b) => a.name.localeCompare(b.name);
    return { meters: meters.sort(byName), devices: devices.sort(byName) };
  }

  _fillPickers() {
    const { meters, devices } = this._candidates();
    const key = meters.map((m) => m.id).join() + "|" + devices.map((d) => d.id).join();
    if (key === this._pickKey) return;
    this._pickKey = key;
    this._devices = devices;
    const meter = this.$("meter");
    const keep = meter.value || this._info.power_entity;
    meter.replaceChildren(
      ...meters.map((m) => el("option", { value: m.id, textContent: `${m.name} (${m.id})` })),
    );
    if (keep && meters.some((m) => m.id === keep)) meter.value = keep;
    this._fillDevices();
    this._updateMeterNow();
  }

  _fillDevices() {
    const text = this.$("filter").value.trim().toLowerCase();
    const select = this.$("device");
    const keep = select.value;
    const shown = (this._devices || [])
      .filter((d) => !text || d.name.toLowerCase().includes(text) || d.id.includes(text))
      .slice(0, 300);
    select.replaceChildren(
      ...shown.map((d) => el("option", { value: d.id, textContent: `${d.name} (${d.id})` })),
    );
    if (shown.some((d) => d.id === keep)) select.value = keep;
    this._updatePlan();
  }

  _updateMeterNow() {
    const id = this.$("meter").value;
    const state = id && this._hass?.states[id];
    this.$("meterNow").textContent = state
      ? `Now: ${state.state} ${state.attributes.unit_of_measurement || ""}`
      : "";
  }

  _updatePlan() {
    const settle = Number(this.$("settle").value) || 0;
    const window_ = Number(this.$("window").value) || 0;
    const cycles = Number(this.$("cycles").value) || 1;
    const seconds = (settle + window_) * (2 * cycles + 1);
    const minutes = Math.max(1, Math.round(seconds / 60));
    const device = this.$("device").value;
    this.$("plan").textContent = device
      ? `This switches ${device} off, then on, then off again. About ${minutes} minute${minutes === 1 ? "" : "s"}.`
      : "Choose a device to test.";
    this.$("start").disabled = !device || this._progress?.state === "measuring";
  }

  async _start() {
    const error = this.$("startError");
    error.hidden = true;
    const msg = {
      type: "power_probe/start",
      entity_id: this.$("device").value,
      power_entity: this.$("meter").value || undefined,
      settle_time: Number(this.$("settle").value),
      sample_window: Number(this.$("window").value),
      sample_interval: Number(this.$("interval").value),
      cycles: Number(this.$("cycles").value),
      restore_state: this.$("restore").checked,
    };
    this._cycles = msg.cycles;
    this._awaiting = true;
    this._shown = null;
    this.$("result").hidden = true;
    try {
      await this._hass.callWS(msg);
    } catch (err) {
      this._awaiting = false;
      error.textContent = ERRORS[err.code] || err.message || ERRORS.unknown;
      error.hidden = false;
    }
  }

  _renderProgress() {
    const p = this._progress;
    const running = p?.state === "measuring";
    this.$("progress").hidden = !running;
    this.$("setup").hidden = running;
    if (!running) {
      this._updatePlan();
      return;
    }
    const cycles = this._cycles || Number(this.$("cycles").value) || 1;
    const names = ["off_1"];
    for (let c = 1; c <= cycles; c++) names.push(`on_${c}`, `off_${c + 1}`);
    const total = names.length;
    const at = names.indexOf(p.step);
    this.$("progressTitle").textContent = `Measuring ${p.entity_id}`;
    this.$("steps").replaceChildren(
      ...names.map((name, i) => {
        const cls = i < at ? "done" : i === at ? "current" : "";
        return el("li", { className: cls }, el("span", { className: "dot" }), stepLabel(name, total));
      }),
    );
    this.$("bar").style.width = `${p.percent}%`;
    const bits = [];
    if (p.activity) bits.push(ACTIVITY[p.activity] || p.activity);
    if (p.latest_w !== null && p.latest_w !== undefined) bits.push(`house now ${watts(p.latest_w)}`);
    if (p.seconds_left !== null && p.seconds_left !== undefined) bits.push(`about ${p.seconds_left} s left`);
    this.$("progressText").textContent = bits.join(", ");
  }

  _showFailure() {
    this._awaiting = false;
    const code = this._progress.error;
    const card = this.$("result");
    card.replaceChildren(
      el("h2", { textContent: "The measurement did not finish" }),
      el("p", { textContent: ERRORS[code] || ERRORS.unknown }),
    );
    card.hidden = false;
  }

  _showResult(r) {
    this._shown = r.id;
    const card = this.$("result");
    const kids = [];
    kids.push(el("h2", { textContent: `${r.name}` }));
    const big = el("div", { className: "big" });
    big.append(watts(r.power_w), " ", el("small", { textContent: `± ${watts(r.uncertainty_w)}` }));
    big.append(el("span", { className: `badge ${r.quality}`, textContent: QUALITY_TEXT[r.quality] }));
    kids.push(big);

    if (r.quality !== "good" && WHY[r.limiting]) {
      kids.push(el("p", { className: "muted", textContent: WHY[r.limiting] }));
    }
    for (const w of r.warnings) {
      if (WARNINGS[w]) kids.push(el("p", { className: "error", textContent: WARNINGS[w] }));
    }

    const stat = (label, value) =>
      el("div", { className: "stat" }, label, el("b", { textContent: value }));
    kids.push(
      el(
        "div",
        { className: "stats" },
        stat("House, device off", watts(r.off_start_w)),
        stat("House, device on", watts(r.on_w)),
        stat("House, off again", watts(r.off_end_w)),
        stat("Drift", watts(r.drift_w)),
      ),
    );

    if (r.powercalc_yaml) {
      const pre = el("pre", { textContent: r.powercalc_yaml });
      const copy = el("button", { className: "secondary", textContent: "Copy YAML" });
      copy.addEventListener("click", async () => {
        try {
          await navigator.clipboard.writeText(r.powercalc_yaml);
          copy.textContent = "Copied";
        } catch (err) {
          copy.textContent = "Select the text and copy it";
        }
      });
      kids.push(
        el("h2", { textContent: "Use it with Powercalc" }),
        el("p", {
          className: "muted",
          textContent:
            "Add this to configuration.yaml, or in Powercalc's own UI add a virtual power sensor for the device, choose the fixed strategy and enter the watts. If the device keeps drawing power while it is off (a smart bulb, for example), add standby_power to the sensor as well.",
        }),
        pre,
        el("div", { className: "actions" }, copy),
      );
    }
    card.replaceChildren(...kids);
    card.hidden = false;
  }

  _renderHistory() {
    const box = this.$("history");
    this.$("historyCard").hidden = this._history.length === 0;
    box.replaceChildren(
      ...this._history.map((r) => {
        const when = new Date(r.finished_at).toLocaleString();
        const grow = el(
          "div",
          { className: "grow" },
          el("span", { textContent: `${r.name}: ${watts(r.power_w)} (${QUALITY_TEXT[r.quality]})` }),
          el("span", { className: "muted", textContent: when }),
        );
        grow.addEventListener("click", () => {
          this._showResult(r);
          this.$("result").scrollIntoView({ behavior: "smooth" });
        });
        const del = el("button", { className: "secondary", textContent: "Delete" });
        del.addEventListener("click", () => {
          this._hass.callWS({ type: "power_probe/delete", id_: r.id });
          if (this._shown === r.id) this.$("result").hidden = true;
        });
        return el("div", { className: "hist" }, grow, del);
      }),
    );
  }
}

customElements.define("power-probe-panel", PowerProbePanel);
