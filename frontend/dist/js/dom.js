// Minimal DOM helpers and shared presentational pieces (no framework).
export function h(tag, attrs = null, ...children) {
    const el = document.createElement(tag);
    if (attrs) {
        for (const [k, v] of Object.entries(attrs)) {
            if (v === undefined || v === null || v === false)
                continue;
            if (k.startsWith("on") && typeof v === "function") {
                el.addEventListener(k.slice(2).toLowerCase(), v);
            }
            else if (k === "class") {
                el.className = String(v);
            }
            else if (k === "dataset") {
                Object.assign(el.dataset, v);
            }
            else if (v === true) {
                el.setAttribute(k, "");
            }
            else {
                el.setAttribute(k, String(v));
            }
        }
    }
    append(el, children);
    return el;
}
export function append(el, children) {
    for (const c of children) {
        if (c === null || c === undefined || c === false)
            continue;
        if (Array.isArray(c))
            append(el, c);
        else
            el.appendChild(c instanceof Node ? c : document.createTextNode(String(c)));
    }
}
const SVGNS = "http://www.w3.org/2000/svg";
export function s(tag, attrs = {}, ...children) {
    const el = document.createElementNS(SVGNS, tag);
    for (const [k, v] of Object.entries(attrs))
        if (v !== undefined)
            el.setAttribute(k, String(v));
    for (const c of children) {
        if (c === null)
            continue;
        el.appendChild(typeof c === "string" ? document.createTextNode(c) : c);
    }
    return el;
}
export function clear(el) {
    while (el.firstChild)
        el.removeChild(el.firstChild);
}
// ---- time ---------------------------------------------------------------
const TZ = "Asia/Kolkata";
const fmtFull = new Intl.DateTimeFormat("en-IN", { timeZone: TZ, day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit", hour12: false });
const fmtTime = new Intl.DateTimeFormat("en-IN", { timeZone: TZ, hour: "2-digit", minute: "2-digit", hour12: false });
const fmtDate = new Intl.DateTimeFormat("en-IN", { timeZone: "UTC", day: "numeric", month: "short", year: "numeric" });
export function when(iso) {
    if (!iso)
        return h("span", { class: "muted" }, "—");
    return h("time", { datetime: iso, title: `${iso} (UTC)` }, `${fmtFull.format(new Date(iso))} IST`);
}
export function timeOnly(iso) { return fmtTime.format(new Date(iso)); }
export function dateOnly(isoDate) { return fmtDate.format(new Date(isoDate + "T00:00:00Z")); }
export function ago(iso, now = Date.now()) {
    if (!iso)
        return "never";
    const s = Math.round((now - new Date(iso).getTime()) / 1000);
    if (s < 0)
        return "just now";
    if (s < 90)
        return `${s} s ago`;
    if (s < 5400)
        return `${Math.round(s / 60)} min ago`;
    if (s < 172800)
        return `${(s / 3600).toFixed(1)} h ago`;
    return `${Math.round(s / 86400)} d ago`;
}
export function fmtNum(v, unit = "") {
    if (v === null || v === undefined)
        return "—";
    const n = Math.abs(v) >= 100 ? v.toFixed(0) : Math.abs(v) >= 10 ? v.toFixed(1) : v.toFixed(2).replace(/\.?0+$/, "") || "0";
    return unit ? `${n} ${unit}` : n;
}
// ---- vocabulary ---------------------------------------------------------
export const HAZARD = { landslide: "Landslide", flash_flood: "Flash flood" };
export const TIER_LABEL = { LOW: "Low", ELEVATED: "Elevated", HIGH: "High", INSUFFICIENT_DATA: "Insufficient data" };
export const STATUS_LABEL = {
    REVIEW_REQUIRED: "Review required", ACKNOWLEDGED: "Acknowledged", ACTION_ASSIGNED: "Action assigned", RESOLVED: "Resolved",
};
export const SENSOR_LABEL = {
    rain_gauge: "Rain gauge", soil_moisture: "Soil moisture", extensometer: "Extensometer", river_stage: "River stage",
};
// Risk tier + reliability are always shown together but as separate parts.
export function riskChip(tier, reliability, opts = {}) {
    const t = tier || "NONE";
    const bars = reliability === "GOOD" ? 3 : reliability === "DEGRADED" ? 2 : reliability === "POOR" ? 1 : 0;
    const relText = reliability ? `Data reliability: ${reliability.toLowerCase()}` : "";
    return h("span", { class: `risk tier-${t}${opts.compact ? " compact" : ""}`, title: [TIER_LABEL[t] || "Not assessed", relText].filter(Boolean).join(". ") }, h("span", { class: "risk-tier" }, (TIER_LABEL[t] || "Not assessed") + (opts.lowerBound ? " +" : "")), reliability ? h("span", { class: `risk-rel rel-${reliability}`, "aria-label": relText }, h("i", { class: bars >= 1 ? "on" : "" }), h("i", { class: bars >= 2 ? "on" : "" }), h("i", { class: bars >= 3 ? "on" : "" }), opts.compact ? null : h("span", { class: "rel-text" }, reliability.toLowerCase())) : null);
}
export function originTag(origin) {
    const o = origin || "NONE";
    const label = { SIMULATED: "Simulated", OBSERVED: "Observed", IMPORTED: "Imported", MIXED: "Mixed sources", DERIVED: "Derived", SYNTHETIC: "Synthetic", NONE: "No data" };
    return h("span", { class: `origin origin-${o}`, title: o === "SIMULATED" || o === "SYNTHETIC" ? "Generated for demonstration — not a real measurement or event" : "" }, label[o] || o);
}
export function statePill(state) {
    const label = { FRESH: "Reporting", STALE: "Stale", OFFLINE: "Offline", NO_DATA: "No data", MAINTENANCE: "Maintenance",
        HEALTHY: "Healthy", DEGRADED: "Degraded", UNAVAILABLE: "Unavailable", NOT_CONFIGURED: "Not configured", UNKNOWN: "Unknown",
        available: "Current", stale: "Stale", missing: "Missing", incomplete: "Incomplete" };
    return h("span", { class: `state state-${state}` }, label[state] || state);
}
export function statusPill(status) {
    return h("span", { class: `status status-${status}` }, STATUS_LABEL[status] || status);
}
export function empty(title, body, action) {
    return h("div", { class: "empty" }, h("p", { class: "empty-title" }, title), body ? h("p", null, body) : null, action || null);
}
export function loading(label = "Loading") {
    return h("div", { class: "loading", role: "status" }, h("span", { class: "spinner", "aria-hidden": "true" }), label + "…");
}
export function section(title, ...children) {
    return h("section", { class: "panel" }, h("h2", null, title), ...children);
}
export function kv(rows) {
    return h("dl", { class: "kv" }, rows.map(([k, v]) => [h("dt", null, k), h("dd", null, v)]));
}
export function toast(message, kind = "ok") {
    const host = document.getElementById("toasts");
    if (!host)
        return;
    const t = h("div", { class: `toast toast-${kind}`, role: kind === "error" ? "alert" : "status" }, message);
    host.appendChild(t);
    setTimeout(() => t.remove(), 5000);
}
// Accessible confirmation dialog built on <dialog>.
export function confirmDialog(opts) {
    const err = h("p", { class: "form-error", role: "alert" });
    const btn = h("button", { class: opts.danger ? "btn btn-danger" : "btn btn-primary", type: "submit" }, opts.confirm);
    const dlg = h("dialog", { class: "dialog" }, h("form", { method: "dialog", onsubmit: async (e) => {
            e.preventDefault();
            btn.setAttribute("disabled", "");
            err.textContent = "";
            try {
                await opts.onConfirm();
                dlg.close();
                dlg.remove();
            }
            catch (ex) {
                err.textContent = ex.message;
                btn.removeAttribute("disabled");
            }
        } }, h("h2", null, opts.title), h("div", { class: "dialog-body" }, opts.body), opts.form || null, err, h("div", { class: "dialog-actions" }, h("button", { class: "btn", type: "button", onclick: () => { dlg.close(); dlg.remove(); } }, "Cancel"), btn)));
    // Escape closes a native <dialog> without our handlers running; remove it on any close so stale
    // dialogs (and their duplicate form fields) never accumulate in the page (HDEWS-028).
    dlg.addEventListener("close", () => dlg.remove());
    document.body.appendChild(dlg);
    dlg.showModal();
    const first = dlg.querySelector("textarea, input, select");
    (first || btn).focus();
}
export function render(root, ...children) {
    clear(root);
    append(root, children);
}
// Only http(s) links from data are rendered as links; anything else (e.g. javascript:) is not (HDEWS-022).
export function safeUrl(url) {
    if (!url)
        return null;
    try {
        const u = new URL(url, location.href);
        return u.protocol === "https:" || u.protocol === "http:" ? u.href : null;
    }
    catch {
        return null;
    }
}
