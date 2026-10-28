import { api, can } from "../api.js";
import { render, h, riskChip, HAZARD, toast, SENSOR_LABEL, ago, originTag } from "../dom.js";
import { pageHead } from "../ui.js";

interface Slider { key: string; label: string; unit: string; min: number; max: number; step: number }
const SLIDERS: Slider[] = [
  { key: "rain_mm_h", label: "Current rainfall intensity", unit: "mm/h", min: 0, max: 80, step: 1 },
  { key: "rain_hours", label: "Duration of current rainfall", unit: "h", min: 0, max: 24, step: 0.5 },
  { key: "background_rain_mm_h", label: "Earlier rainfall in last 24 h", unit: "mm/h", min: 0, max: 15, step: 0.5 },
  { key: "soil_moisture_pct", label: "Soil moisture", unit: "% VWC", min: 10, max: 60, step: 0.5 },
  { key: "displacement_24h_mm", label: "Slope displacement over 24 h", unit: "mm", min: 0, max: 20, step: 0.1 },
  { key: "river_level_m", label: "River stage now", unit: "m", min: 0, max: 7, step: 0.05 },
  { key: "river_rise_1h_m", label: "River rise in the last hour", unit: "m", min: -0.5, max: 2, step: 0.05 },
  { key: "delay_minutes", label: "Delay for delayed sensors", unit: "min", min: 0, max: 180, step: 5 },
  { key: "outage_minutes", label: "Outage length for offline sensors", unit: "min", min: 0, max: 720, step: 15 },
];

export async function simulatorPage(root: HTMLElement, params: URLSearchParams): Promise<void> {
  const meta = await api("/api/demo/presets");
  const allowed = can("run_scenario");
  const preselect = params.get("site");
  const selected = new Set<string>(preselect ? [preselect] : [meta.sites[0].id]);
  let preset = "rising_landslide_indicators";
  const values: Record<string, number> = {};
  const offline = new Set<string>(), delayed = new Set<string>();
  const result = h("div", { class: "sim-result", "aria-live": "polite" });

  const presetParams = (id: string) => {
    const p = { ...meta.presets.find((x: any) => x.id === id).params };
    const site = meta.sites.find((s: any) => selected.has(s.id)) || meta.sites[0];
    const defaults: Record<string, number> = {};
    for (const [k, v] of Object.entries(meta.parameters as Record<string, any>)) if (typeof v.default === "number") defaults[k] = v.default;
    const out: Record<string, any> = { ...defaults, ...p };
    out.river_level_m = +(site.normal_river_level_m + (p.river_offset_m || 0)).toFixed(2);
    return out;
  };
  const loadPreset = (id: string) => {
    preset = id;
    const p = presetParams(id);
    for (const sl of SLIDERS) values[sl.key] = p[sl.key] ?? 0;
    offline.clear(); delayed.clear();
    (p.offline_sensors || []).forEach((t: string) => offline.add(t));
    (p.delayed_sensors || []).forEach((t: string) => delayed.add(t));
  };
  loadPreset(preset);

  const sliderEls: Record<string, HTMLInputElement> = {};
  const outputs: Record<string, HTMLOutputElement> = {};
  const sliderBlock = h("div", { class: "sliders" }, SLIDERS.map(sl => {
    const input = h("input", { type: "range", id: `sl-${sl.key}`, min: sl.min, max: sl.max, step: sl.step, value: values[sl.key],
      disabled: !allowed, oninput: (e: Event) => { values[sl.key] = Number((e.target as HTMLInputElement).value); outputs[sl.key].value = `${values[sl.key]} ${sl.unit}`; markCustom(); } });
    sliderEls[sl.key] = input;
    outputs[sl.key] = h("output", { for: `sl-${sl.key}` }, `${values[sl.key]} ${sl.unit}`);
    return h("div", { class: "slider" }, h("label", { for: `sl-${sl.key}` }, sl.label), input, outputs[sl.key]);
  }));
  const connBoxes: HTMLInputElement[] = [];
  const connectivity = h("table", { class: "compact conn" },
    h("thead", null, h("tr", null, h("th", null, "Sensor type"), h("th", null, "Offline"), h("th", null, "Delayed"))),
    h("tbody", null, meta.sensor_types.map((t: string) => {
      const off = h("input", { type: "checkbox", "aria-label": `${SENSOR_LABEL[t]} offline`, checked: offline.has(t), disabled: !allowed,
        onchange: (e: Event) => { (e.target as HTMLInputElement).checked ? offline.add(t) : offline.delete(t); markCustom(); } });
      const del = h("input", { type: "checkbox", "aria-label": `${SENSOR_LABEL[t]} delayed`, checked: delayed.has(t), disabled: !allowed,
        onchange: (e: Event) => { (e.target as HTMLInputElement).checked ? delayed.add(t) : delayed.delete(t); markCustom(); } });
      off.dataset.type = t; off.dataset.kind = "off"; del.dataset.type = t; del.dataset.kind = "del";
      connBoxes.push(off, del);
      return h("tr", null, h("td", null, SENSOR_LABEL[t]), h("td", null, off), h("td", null, del));
    })));
  const syncControls = () => {
    for (const sl of SLIDERS) { sliderEls[sl.key].value = String(values[sl.key]); outputs[sl.key].value = `${values[sl.key]} ${sl.unit}`; }
    for (const b of connBoxes) b.checked = (b.dataset.kind === "off" ? offline : delayed).has(b.dataset.type!);
  };
  let custom = false;
  const customNote = h("p", { class: "muted small" });
  function markCustom() { custom = true; customNote.textContent = "Custom values — the preset has been modified."; }

  const presetList = h("div", { class: "preset-list", role: "radiogroup", "aria-label": "Scenario preset" }, meta.presets.map((p: any) =>
    h("label", { class: "preset" },
      h("input", { type: "radio", name: "preset", value: p.id, checked: p.id === preset, disabled: !allowed,
        onchange: () => { loadPreset(p.id); custom = false; customNote.textContent = ""; syncControls(); } }),
      h("span", null, h("strong", null, p.label), h("span", { class: "muted small" }, p.description)))));

  const siteBoxes = h("fieldset", { class: "site-select" }, h("legend", null, "Apply to sites"),
    meta.sites.map((s: any) => h("label", null,
      h("input", { type: "checkbox", checked: selected.has(s.id), disabled: !allowed,
        onchange: (e: Event) => { (e.target as HTMLInputElement).checked ? selected.add(s.id) : selected.delete(s.id); } }),
      ` ${s.name} `, h("span", { class: "muted small" }, s.hazards.map((x: string) => HAZARD[x]).join(", "),
        s.sim_state ? `; now: ${s.sim_state.preset?.replace(/_/g, " ") || "custom"}, ${ago(s.sim_state.applied_at)}` : ""))));

  const applyBtn = h("button", { class: "btn btn-primary", type: "button", disabled: !allowed, onclick: async () => {
    if (!selected.size) { toast("Select at least one site.", "error"); return; }
    applyBtn.setAttribute("disabled", "");
    result.replaceChildren(h("p", { class: "muted" }, "Generating simulated readings and re-assessing…"));
    const overrides: Record<string, any> = { ...values, offline_sensors: [...offline], delayed_sensors: [...delayed] };
    try {
      const r = await api("/api/demo/scenario", { method: "POST", body: { site_ids: [...selected], preset, overrides: custom ? overrides : undefined,
        name: custom ? `Custom (${meta.presets.find((p: any) => p.id === preset).label} modified)` : undefined } });
      const alerts = await api("/api/alerts?status=REVIEW_REQUIRED&limit=50");
      const mine = alerts.items.filter((a: any) => selected.has(a.site_id));
      result.replaceChildren(
        h("h3", null, `Scenario applied: ${r.name}`),
        h("p", { class: "small" }, `${Object.values(r.sites as Record<string, any>).reduce((n: number, s: any) => n + s.observations_written, 0)} simulated observations written. Backend assessments:`),
        h("table", { class: "compact" }, h("thead", null, h("tr", null, h("th", null, "Site"), h("th", null, "Hazard"), h("th", null, "Result"), h("th", null, "Summary"))),
          h("tbody", null, r.assessments.map((a: any) => h("tr", null, h("td", null, h("a", { href: `#/sites/${a.site_id}` }, a.site_id)), h("td", null, HAZARD[a.hazard]),
            h("td", null, riskChip(a.risk_tier, a.reliability)), h("td", { class: "small" }, a.summary))))),
        mine.length ? h("div", { class: "callout callout-warn" }, h("strong", null, `${mine.length} candidate alert${mine.length > 1 ? "s" : ""} awaiting review: `),
          h("ul", { class: "plain" }, mine.map((a: any) => h("li", null, h("a", { href: `#/alerts/${a.id}` }, a.title))))) :
          h("p", { class: "muted small" }, "No new candidate alerts awaiting review for these sites."));
      toast("Scenario applied. All generated readings are labelled simulated.");
    } catch (err) {
      result.replaceChildren(h("p", { class: "form-error", role: "alert" }, (err as Error).message));
    }
    applyBtn.removeAttribute("disabled");
  } }, "Apply scenario and re-assess");

  render(root, 
    h("div", { class: "sim-banner", role: "note" }, h("strong", null, "Simulation mode. "), meta.note, " Applying a scenario replaces the selected sites' simulated readings and is recorded in the audit log."),
    pageHead("Scenario simulator", "Change environmental inputs for demo sites. The backend regenerates 48 h of simulated telemetry and the rule engine re-assesses immediately."),
    !allowed ? h("p", { class: "callout" }, "Your role can view scenarios but not apply them. Sign in as an analyst or administrator to run the simulator.") : null,
    h("div", { class: "sim-layout" },
      h("div", null, h("h2", { class: "section-title" }, "Preset"), presetList, siteBoxes),
      h("div", null, h("h2", { class: "section-title" }, "Inputs"), customNote, sliderBlock,
        h("p", { class: "muted small" }, "Unmodified presets set river stage relative to each site's normal stage; once you change any input, the values shown apply as-is to every selected site."),
        h("h3", null, "Sensor connectivity"), connectivity,
        h("div", { class: "sim-apply" }, applyBtn, h("span", { class: "muted small" }, "Readings will be tagged ", originTag("SIMULATED"))),
        result)));
}
