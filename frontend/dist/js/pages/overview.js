import { api } from "../api.js";
import { render, h, riskChip, originTag, when, ago, HAZARD, TIER_LABEL, fmtNum, empty, dateOnly } from "../dom.js";
import { hourlyBars } from "../charts.js";
import { createMap } from "../map.js";
import { pageHead } from "../ui.js";
async function drawOverview(root) {
    const [o, layers] = await Promise.all([api("/api/overview"), api("/api/map/layers")]);
    const siteName = (id) => o.sites.find((x) => x.id === id)?.name || id;
    const review = o.open_alerts.filter((a) => a.status === "REVIEW_REQUIRED");
    const inProgress = o.open_alerts.filter((a) => a.status !== "REVIEW_REQUIRED");
    const queue = h("section", { class: "panel queue" }, h("h2", null, "Candidate alerts awaiting review"), review.length
        ? h("ul", { class: "queue-list" }, review.map((a) => h("li", null, h("a", { href: `#/alerts/${a.id}` }, h("span", { class: `kind kind-${a.kind}` }, a.kind === "HAZARD" ? "Hazard" : "Data gap"), " ", a.title), h("span", { class: "muted small" }, " raised ", ago(a.created_at)), " ", originTag(a.data_origin))))
        : h("p", { class: "muted" }, "Nothing awaiting review."), inProgress.length ? h("p", { class: "small" }, `${inProgress.length} more open alert${inProgress.length > 1 ? "s" : ""} in progress. `, h("a", { href: "#/alerts" }, "Open the alert queue")) : null);
    const matrix = h("section", { class: "panel" }, h("h2", null, "Current assessment by site"), h("div", { class: "table-scroll" }, h("table", { class: "matrix" }, h("thead", null, h("tr", null, h("th", null, "Site"), h("th", null, "Landslide"), h("th", null, "Flash flood"), h("th", null, "Data"), h("th", null, "Scenario"))), h("tbody", null, o.sites.map((s) => h("tr", null, h("th", { scope: "row" }, h("a", { href: `#/sites/${s.id}` }, s.name), h("div", { class: "muted small" }, s.id)), ...["landslide", "flash_flood"].map(hz => h("td", null, s.latest[hz]
        ? h("a", { href: `#/sites/${s.id}`, class: "chip-link", title: s.latest[hz].summary }, riskChip(s.latest[hz].risk_tier, s.latest[hz].reliability, { lowerBound: s.latest[hz].tier_is_lower_bound }))
        : h("span", { class: "muted small" }, "not monitored"))), h("td", null, originTag(Object.values(s.latest)[0]?.data_origin)), h("td", { class: "small" }, s.scenario ? `${s.scenario.preset?.replace(/_/g, " ") || "custom"}, ${ago(s.scenario.applied_at)}` : "—")))))), h("p", { class: "muted small legend-line" }, "Tier and data reliability are separate: the bars show reliability (3 = good, 2 = degraded, 1 = poor). A “+” marks a tier that may understate risk because inputs are missing."));
    const sensorTotal = o.sensor_total;
    const order = ["FRESH", "STALE", "OFFLINE", "NO_DATA", "MAINTENANCE"];
    const health = h("section", { class: "panel" }, h("h2", null, "Sensor connectivity"), h("div", { class: "stack-bar", role: "img", "aria-label": order.filter(k => o.sensor_states[k]).map(k => `${o.sensor_states[k]} ${k.toLowerCase()}`).join(", ") }, order.filter(k => o.sensor_states[k]).map(k => h("span", { class: `seg seg-${k}`, style: `flex:${o.sensor_states[k]}`, title: `${k}: ${o.sensor_states[k]}` }))), h("ul", { class: "count-list" }, order.filter(k => o.sensor_states[k]).map(k => h("li", null, h("span", { class: `swatch seg-${k}` }), `${o.sensor_states[k]} ${{ FRESH: "reporting", STALE: "stale", OFFLINE: "offline", NO_DATA: "no data", MAINTENANCE: "in maintenance" }[k]}`))), h("p", { class: "muted small" }, `${sensorTotal} sensors across ${o.sites.length} sites. Observations in the last 24 h by origin: `, Object.entries(o.observation_origin_counts_24h).map(([k, v]) => `${v} ${k.toLowerCase()}`).join(", ") || "none", "."));
    const mapHost = h("section", { class: "panel map-preview" }, h("h2", null, h("a", { href: "#/map" }, "Pilot area map")));
    const m = createMap({ data: layers, layers: { sites: true, rivers: true, hazard_zones: false, incidents: false, places: true }, tiles: false, height: 300,
        onSite: (id) => { location.hash = `#/sites/${id}`; } });
    mapHost.appendChild(m.el);
    const maxRain = Math.max(1, ...Object.values(o.rain_hourly.series).flat());
    const rain = h("section", { class: "panel" }, h("h2", null, "Rainfall, last 24 hours"), h("p", { class: "muted small" }, "Hourly totals from site rain gauges (mm per hour), shared scale. Bars at 15 mm/h or more are highlighted. Each gauge shows one origin; observed readings take precedence over simulated ones."), h("div", { class: "rain-grid" }, Object.entries(o.rain_hourly.series).map(([id, vals]) => h("div", { class: "rain-cell" }, h("div", { class: "rain-head" }, h("a", { href: `#/sites/${id}` }, siteName(id)), h("span", { class: "num" }, fmtNum(vals.reduce((a, b) => a + b, 0), "mm"), " ", originTag(o.rain_hourly.origin?.[id] || "NONE"))), hourlyBars({ hours: o.rain_hourly.hours, values: vals, unit: "mm", label: siteName(id), max: Math.ceil(maxRain / 5) * 5 })))));
    const changes = h("section", { class: "panel" }, h("h2", null, "Recent tier changes"), o.tier_changes.length ? h("ol", { class: "timeline" }, o.tier_changes.map((c) => h("li", null, h("span", { class: "muted small" }, when(c.occurred_at)), " ", h("a", { href: `#/sites/${c.site_id}` }, siteName(c.site_id)), ` ${HAZARD[c.hazard]}: `, c.previous_tier ? `${TIER_LABEL[c.previous_tier] || c.previous_tier} → ` : "", h("strong", null, TIER_LABEL[c.risk_tier] || c.risk_tier), h("span", { class: "muted small" }, ` (reliability ${c.reliability.toLowerCase()})`)))) : empty("No changes yet."));
    const recent = h("section", { class: "panel" }, h("h2", null, "Latest observations received"), h("div", { class: "table-scroll" }, h("table", { class: "compact" }, h("thead", null, h("tr", null, h("th", null, "Sensor"), h("th", null, "Value"), h("th", null, "Observed"), h("th", null, "Origin"))), h("tbody", null, o.recent_observations.map((r) => h("tr", null, h("td", null, h("a", { href: `#/sites/${r.site_id}` }, r.sensor_id)), h("td", { class: "num" }, fmtNum(r.value, r.unit)), h("td", null, when(r.observed_at)), h("td", null, originTag(r.origin))))))));
    const incidents = h("section", { class: "panel" }, h("h2", null, h("a", { href: "#/incidents" }, "Historical incidents")), h("ul", { class: "plain" }, o.recent_incidents.map((i) => h("li", null, h("a", { href: `#/incidents?id=${i.id}` }, i.title), " ", h("span", { class: "muted small" }, dateOnly(i.event_date)), " ", originTag(i.origin)))));
    render(root, pageHead("Overview", [`${o.pilot_area}. Data mode: `, originTag(o.data_mode), ` Updated `, when(o.generated_at), "."], [
        h("button", { class: "btn", type: "button", onclick: () => drawOverview(root) }, "Refresh")
    ]), h("div", { class: "grid-overview" }, h("div", { class: "col-main" }, queue, matrix, rain), h("div", { class: "col-side" }, mapHost, health, changes, recent, incidents)));
}
export async function overviewPage(root) {
    await drawOverview(root);
    const timer = setInterval(() => { if (document.visibilityState === "visible")
        drawOverview(root).catch(() => { }); }, 60000);
    return () => clearInterval(timer);
}
