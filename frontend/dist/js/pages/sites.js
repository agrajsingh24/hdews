import { api, can } from "../api.js";
import { render, h, riskChip, originTag, when, ago, HAZARD, statePill, statusPill, fmtNum, empty, toast, dateOnly, kv, SENSOR_LABEL } from "../dom.js";
import { lineChart } from "../charts.js";
import { createMap, worstTier } from "../map.js";
import { pageHead, assessmentCard, sensorCard } from "../ui.js";
const explain = (id) => api(`/api/assessments/${id}/explanation`);
export async function sitesPage(root) {
    const data = await api("/api/sites");
    render(root, pageHead("Monitoring sites", "Simulated monitoring points in the Rudraprayag pilot area. Coordinates are approximate locality points; no physical sensors are installed."), h("div", { class: "site-cards" }, data.items.map((s) => {
        const counts = {};
        s.sensor_states.forEach((st) => counts[st] = (counts[st] || 0) + 1);
        return h("a", { class: "card site-card", href: `#/sites/${s.id}` }, h("div", { class: "site-card-head" }, h("h2", null, s.name), h("span", { class: "muted small" }, s.id)), h("p", { class: "muted small" }, `${s.latitude.toFixed(4)}°N, ${s.longitude.toFixed(4)}°E, ${s.elevation_m} m`), h("ul", { class: "plain" }, s.hazards.map((hz) => h("li", { class: "hz-row" }, h("span", null, HAZARD[hz]), riskChip(s.assessments[hz]?.risk_tier, s.assessments[hz]?.reliability, { lowerBound: s.assessments[hz]?.tier_is_lower_bound })))), h("p", { class: "small" }, Object.entries(counts).map(([k, v]) => [statePill(k), ` ${v} `])), h("p", { class: "small muted" }, s.scenario ? `Simulated scenario: ${s.scenario.preset?.replace(/_/g, " ") || "custom"} (${ago(s.scenario.applied_at)})` : ""));
    })));
}
function chartFor(series, cfg, hours) {
    const pts = series.points;
    const gap = series.expected_interval_s;
    const thr = [];
    if (series.sensor_type === "river_stage") {
        thr.push({ value: cfg.flash_flood.river_warning_level_m, label: "warning stage (demo)", kind: "watch" }, { value: cfg.flash_flood.river_danger_level_m, label: "danger stage (demo)", kind: "high" });
    }
    if (series.sensor_type === "soil_moisture") {
        const b = cfg.landslide.soil_moisture_baseline_pct;
        thr.push({ value: b + cfg.landslide.soil_moisture_excess_pct.watch, label: "watch (demo)", kind: "watch" }, { value: b + cfg.landslide.soil_moisture_excess_pct.high, label: "high (demo)", kind: "high" });
    }
    const labels = {
        rain_gauge: "Rainfall per 15-min interval", soil_moisture: "Soil moisture", extensometer: "Cumulative displacement", river_stage: "River stage",
    };
    return lineChart({ points: pts, unit: series.unit, label: labels[series.sensor_type] || series.label, thresholds: thr, gapS: gap, hours,
        zeroBased: series.sensor_type === "rain_gauge",
        cumulativeNote: series.sensor_type === "extensometer" ? "the 24 h change is what the rules use" : undefined });
}
export async function sitePage(root, id) {
    let hours = 24;
    const draw = async () => {
        const [d, obs] = await Promise.all([api(`/api/sites/${id}`), api(`/api/sites/${id}/observations?hours=${hours}`)]);
        const site = d.site;
        const assessments = Object.values(d.assessments).filter(Boolean);
        const origins = new Set(assessments.map((a) => a.data_origin));
        const rangeSel = h("select", { "aria-label": "Chart time window", onchange: (e) => { hours = Number(e.target.value); draw(); } }, ...[6, 24, 48].map(v => h("option", { value: v, selected: v === hours }, `Last ${v} h`)));
        const actions = [
            can("run_assessment") ? h("button", { class: "btn", type: "button", onclick: async (e) => {
                    e.currentTarget.disabled = true;
                    try {
                        await api(`/api/sites/${id}/assess`, { method: "POST" });
                        toast("Assessment re-run with the latest data.");
                        await draw();
                    }
                    catch (err) {
                        toast(err.message, "error");
                    }
                } }, "Re-run assessment") : null,
            can("run_scenario") ? h("a", { class: "btn", href: `#/simulator?site=${id}` }, "Change simulated inputs") : null,
        ];
        render(root, pageHead(site.name, [`${site.district}, ${site.state}. ${site.latitude.toFixed(4)}°N ${site.longitude.toFixed(4)}°E, ${site.elevation_m} m. `,
            ...[...origins].map(o => originTag(o))], actions), h("p", { class: "callout" }, site.location_note, " ", site.description), h("h2", { class: "section-title" }, "Risk assessment"), h("div", { class: "assess-list" }, site.hazards.map((hz) => assessmentCard(d.assessments[hz], { explain }))), h("h2", { class: "section-title" }, "Sensors"), h("div", { class: "sensor-grid" }, d.sensors.map((sn) => sensorCard(sn))), h("div", { class: "section-title-row" }, h("h2", { class: "section-title" }, "Trends"), rangeSel), h("p", { class: "muted small" }, "Dashed violet lines are simulated readings; filled dots are observed readings pushed by a gateway. Shaded areas mean no data was received. Threshold lines are uncalibrated demo settings."), h("div", { class: "chart-grid" }, obs.series.map((sr) => chartFor(sr, d.effective_config, hours))), h("div", { class: "two-col" }, h("section", { class: "panel" }, h("h2", null, "Alert history"), d.alerts.length ? h("ul", { class: "plain" }, d.alerts.map((a) => h("li", null, h("a", { href: `#/alerts/${a.id}` }, a.title), " ", statusPill(a.status), h("span", { class: "muted small" }, " ", ago(a.created_at))))) : empty("No candidate alerts for this site.")), h("section", { class: "panel" }, h("h2", null, "Related incidents"), d.incidents.length ? h("ul", { class: "plain" }, d.incidents.map((i) => h("li", null, h("a", { href: `#/incidents?id=${i.id}` }, i.title), " ", h("span", { class: "muted small" }, dateOnly(i.event_date)), " ", originTag(i.origin)))) : empty("No incidents linked to this site."))));
    };
    await draw();
    const t = setInterval(() => { if (document.visibilityState === "visible" && !document.querySelector("dialog[open]"))
        draw().catch(() => { }); }, 90000);
    return () => clearInterval(t);
}
export async function assessmentPage(root, id) {
    const a = await api(`/api/assessments/${id}`);
    render(root, pageHead(`Assessment ${a.id}`, [h("a", { href: `#/sites/${a.site_id}` }, a.site_name), `, ${a.hazard_label}. Trigger: ${a.trigger}.`]), assessmentCard(a, { explain, showSite: true }), h("section", { class: "panel" }, h("h2", null, `Evidence observations (${a.evidence_observations.length})`), a.evidence_note ? h("p", { class: "callout callout-warn" }, a.evidence_note) : null, a.evidence_observations.length ? h("div", { class: "table-scroll tall" }, h("table", { class: "compact" }, h("thead", null, h("tr", null, ...["ID", "Sensor", "Value", "Observed", "Received", "Quality", "Origin", "Source"].map(t => h("th", null, t)))), h("tbody", null, [...a.evidence_observations].reverse().map((o) => h("tr", null, h("td", { class: "num" }, String(o.id)), h("td", null, o.sensor_id), h("td", { class: "num" }, fmtNum(o.value, o.unit)), h("td", null, when(o.observed_at)), h("td", null, when(o.received_at)), h("td", null, o.quality_status), h("td", null, originTag(o.origin)), h("td", { class: "small" }, o.source_id)))))) : empty("No stored observations for this assessment.")), h("section", { class: "panel" }, h("h2", null, "Sensor health at assessment time"), h("div", { class: "table-scroll" }, h("table", { class: "compact" }, h("thead", null, h("tr", null, ...["Sensor", "State", "Last observed", "Delay", "Latest value"].map(t => h("th", null, t)))), h("tbody", null, (a.sensor_health || []).map((s) => h("tr", null, h("td", null, `${s.label} (${SENSOR_LABEL[s.sensor_type]})`), h("td", null, statePill(s.state)), h("td", null, when(s.last_observed_at)), h("td", null, s.delay_s === null ? "—" : `${Math.round(s.delay_s / 60)} min`), h("td", { class: "num" }, fmtNum(s.latest_value)))))))), kv([["Rule version", a.rule_version], ["Threshold status", a.threshold_status], ["Playbook", a.playbook_version],
        ["Model", a.model.note], ["Previous assessment", a.previous_assessment_id ? h("a", { href: `#/assessments/${a.previous_assessment_id}` }, a.previous_assessment_id) : "none"]]));
}
const LAYER_LABELS = { sites: "Monitoring sites", hazard_zones: "Demo hazard zones (simulated)", rivers: "Rivers (schematic)", incidents: "Historical incidents", places: "Reference places" };
export async function mapPage(root) {
    const data = await api("/api/map/layers");
    const layers = { sites: true, hazard_zones: true, rivers: true, incidents: true, places: true };
    let tiles = false;
    const drawer = h("aside", { class: "drawer", "aria-live": "polite" });
    const showSite = async (id) => {
        m.setSelected(id);
        drawer.replaceChildren(h("p", { class: "muted" }, "Loading site…"));
        try {
            const d = await api(`/api/sites/${id}`);
            drawer.replaceChildren(h("div", { class: "drawer-head" }, h("h2", null, d.site.name), h("button", { class: "btn btn-icon", type: "button", "aria-label": "Close details", onclick: () => { drawer.replaceChildren(drawerIntro()); m.setSelected(null); } }, "×")), h("p", { class: "muted small" }, `${d.site.latitude.toFixed(4)}°N ${d.site.longitude.toFixed(4)}°E, ${d.site.elevation_m} m`), ...d.site.hazards.map((hz) => {
                const a = d.assessments[hz];
                return h("div", { class: "drawer-assess" }, h("div", { class: "hz-row" }, h("strong", null, HAZARD[hz]), riskChip(a?.risk_tier, a?.reliability, { lowerBound: a?.tier_is_lower_bound })), h("p", { class: "small" }, a?.summary || "Not assessed"), a ? h("p", { class: "muted small" }, "Assessed ", when(a.assessed_at)) : null);
            }), h("h3", null, "Sensors"), h("ul", { class: "plain" }, d.sensors.map((s) => h("li", { class: "hz-row small" }, h("span", null, s.label, ": ", h("strong", null, fmtNum(s.health?.latest_value, s.unit))), statePill(s.health?.state || "NO_DATA")))), h("p", { class: "muted small" }, "Readings are ", originTag(d.sensors[0]?.source?.origin), ". Last data ", ago(d.sensors[0]?.health?.last_observed_at), "."), h("a", { class: "btn btn-primary", href: `#/sites/${id}` }, "Open site details"));
        }
        catch (err) {
            drawer.replaceChildren(h("p", { class: "form-error" }, err.message));
        }
    };
    const m = createMap({ data, layers, tiles, onSite: showSite, height: 600 });
    const drawerIntro = () => h("div", null, h("h2", null, "Select a site"), h("p", { class: "muted" }, "Choose a marker on the map, or tab to it and press Enter, to see its current assessment and sensors."));
    drawer.appendChild(drawerIntro());
    const toggles = h("fieldset", { class: "layer-toggles" }, h("legend", null, "Layers"), Object.keys(layers).map(k => h("label", null, h("input", { type: "checkbox", checked: layers[k], onchange: (e) => { layers[k] = e.target.checked; m.update({ layers }); } }), " ", LAYER_LABELS[k])), h("label", null, h("input", { type: "checkbox", checked: tiles, onchange: (e) => { tiles = e.target.checked; m.update({ tiles }); } }), " Online basemap (OpenStreetMap, needs internet)"));
    const legend = h("div", { class: "legend" }, h("h3", null, "Legend"), h("ul", { class: "plain small" }, ...["HIGH", "ELEVATED", "LOW"].map(t => h("li", null, h("span", { class: `lg-dot tier-fill-${t}` }), ` ${t[0] + t.slice(1).toLowerCase()} (worst hazard at the site)`)), h("li", null, h("span", { class: "lg-dot lg-hatch" }), " Insufficient data"), h("li", null, h("span", { class: "lg-dot lg-dashed" }), " Dashed outline: poor data reliability"), h("li", null, h("span", { class: "lg-ring" }), " Pulsing ring: alert awaiting review"), h("li", null, h("span", { class: "lg-sim" }), " Violet dot: simulated telemetry"), h("li", null, h("span", { class: "lg-diamond" }), " Incident (hollow = synthetic demo record)")), h("h3", null, "Layer sources"), h("ul", { class: "plain small muted" }, Object.entries(data.layers).map(([k, v]) => h("li", null, h("strong", null, v.label), ": ", v.metadata))), h("p", { class: "muted small" }, "Layers generated ", when(data.generated_at), "."));
    render(root, pageHead("Live map", "Rudraprayag pilot study area. Drag to pan, scroll or use the buttons to zoom."), h("div", { class: "map-layout" }, h("div", { class: "map-main" }, m.el, toggles), h("div", { class: "map-side" }, drawer, legend)));
    void worstTier;
    const t = setInterval(async () => {
        if (document.visibilityState !== "visible")
            return;
        try {
            const fresh = await api("/api/map/layers");
            m.update({ data: fresh });
        }
        catch { /* keep last view */ }
    }, 60000);
    return () => clearInterval(t);
}
