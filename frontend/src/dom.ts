// Minimal DOM helpers and shared presentational pieces (no framework).

type Child = Node | string | number | null | undefined | false | Child[];
type Attrs = Record<string, unknown>;

export function h<K extends keyof HTMLElementTagNameMap>(tag: K, attrs: Attrs | null = null, ...children: Child[]): HTMLElementTagNameMap[K] {
  const el = document.createElement(tag);
  if (attrs) {
    for (const [k, v] of Object.entries(attrs)) {
      if (v === undefined || v === null || v === false) continue;
      if (k.startsWith("on") && typeof v === "function") {
        el.addEventListener(k.slice(2).toLowerCase(), v as EventListener);
      } else if (k === "class") {
        el.className = String(v);
      } else if (k === "dataset") {
        Object.assign(el.dataset, v as object);
      } else if (v === true) {
        el.setAttribute(k, "");
      } else {
        el.setAttribute(k, String(v));
      }
    }
  }
  append(el, children);
  return el;
}

export function append(el: Node, children: Child[]): void {
  for (const c of children) {
    if (c === null || c === undefined || c === false) continue;
    if (Array.isArray(c)) append(el, c);
    else el.appendChild(c instanceof Node ? c : document.createTextNode(String(c)));
  }
}

const SVGNS = "http://www.w3.org/2000/svg";
export function s<K extends keyof SVGElementTagNameMap>(tag: K, attrs: Record<string, string | number | undefined> = {}, ...children: (SVGElement | string | null)[]): SVGElementTagNameMap[K] {
  const el = document.createElementNS(SVGNS, tag);
  for (const [k, v] of Object.entries(attrs)) if (v !== undefined) el.setAttribute(k, String(v));
  for (const c of children) {
    if (c === null) continue;
    el.appendChild(typeof c === "string" ? document.createTextNode(c) : c);
  }
  return el;
}

export function clear(el: Element): void {
  while (el.firstChild) el.removeChild(el.firstChild);
}

// ---- time ---------------------------------------------------------------
const TZ = "Asia/Kolkata";
const fmtFull = new Intl.DateTimeFormat("en-IN", { timeZone: TZ, day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit", hour12: false });
const fmtTime = new Intl.DateTimeFormat("en-IN", { timeZone: TZ, hour: "2-digit", minute: "2-digit", hour12: false });
const fmtDate = new Intl.DateTimeFormat("en-IN", { timeZone: "UTC", day: "numeric", month: "short", year: "numeric" });

export function when(iso: string | null | undefined): HTMLElement {
  if (!iso) return h("span", { class: "muted" }, "—");
  return h("time", { datetime: iso, title: `${iso} (UTC)` }, `${fmtFull.format(new Date(iso))} IST`);
}
export function timeOnly(iso: string): string { return fmtTime.format(new Date(iso)); }
export function dateOnly(isoDate: string): string { return fmtDate.format(new Date(isoDate + "T00:00:00Z")); }

export function ago(iso: string | null | undefined, now = Date.now()): string {
  if (!iso) return "never";
  const s = Math.round((now - new Date(iso).getTime()) / 1000);
  if (s < 0) return "just now";
  if (s < 90) return `${s} s ago`;
  if (s < 5400) return `${Math.round(s / 60)} min ago`;
  if (s < 172800) return `${(s / 3600).toFixed(1)} h ago`;
  return `${Math.round(s / 86400)} d ago`;
}

export function fmtNum(v: number | null | undefined, unit = ""): string {
  if (v === null || v === undefined) return "—";
  const n = Math.abs(v) >= 100 ? v.toFixed(0) : Math.abs(v) >= 10 ? v.toFixed(1) : v.toFixed(2).replace(/\.?0+$/, "") || "0";
  return unit ? `${n} ${unit}` : n;
}

// ---- vocabulary ---------------------------------------------------------
export const HAZARD: Record<string, string> = { landslide: "Landslide", flash_flood: "Flash flood" };
export const TIER_LABEL: Record<string, string> = { LOW: "Low", ELEVATED: "Elevated", HIGH: "High", INSUFFICIENT_DATA: "Insufficient data" };
export const STATUS_LABEL: Record<string, string> = {
  REVIEW_REQUIRED: "Review required", ACKNOWLEDGED: "Acknowledged", ACTION_ASSIGNED: "Action assigned", RESOLVED: "Resolved",
};
export const SENSOR_LABEL: Record<string, string> = {
  rain_gauge: "Rain gauge", soil_moisture: "Soil moisture", extensometer: "Extensometer", river_stage: "River stage",
};

// Risk tier + reliability are always shown together but as separate parts.
export function riskChip(tier: string | undefined, reliability?: string, opts: { lowerBound?: boolean; compact?: boolean } = {}): HTMLElement {
  const t = tier || "NONE";
  const bars = reliability === "GOOD" ? 3 : reliability === "DEGRADED" ? 2 : reliability === "POOR" ? 1 : 0;
  const relText = reliability ? `Data reliability: ${reliability.toLowerCase()}` : "";
  return h("span", { class: `risk tier-${t}${opts.compact ? " compact" : ""}`, title: [TIER_LABEL[t] || "Not assessed", relText].filter(Boolean).join(". ") },
    h("span", { class: "risk-tier" }, (TIER_LABEL[t] || "Not assessed") + (opts.lowerBound ? " +" : "")),
    reliability ? h("span", { class: `risk-rel rel-${reliability}`, "aria-label": relText },
      h("i", { class: bars >= 1 ? "on" : "" }), h("i", { class: bars >= 2 ? "on" : "" }), h("i", { class: bars >= 3 ? "on" : "" }),
      opts.compact ? null : h("span", { class: "rel-text" }, reliability.toLowerCase())) : null);
}

export function originTag(origin: string | null | undefined): HTMLElement {
  const o = origin || "NONE";
  const label: Record<string, string> = { SIMULATED: "Simulated", OBSERVED: "Observed", IMPORTED: "Imported", MIXED: "Mixed sources", DERIVED: "Derived", SYNTHETIC: "Synthetic", NONE: "No data" };
  return h("span", { class: `origin origin-${o}`, title: o === "SIMULATED" || o === "SYNTHETIC" ? "Generated for demonstration — not a real measurement or event" : "" }, label[o] || o);
}

export function statePill(state: string): HTMLElement {
  const label: Record<string, string> = { FRESH: "Reporting", STALE: "Stale", OFFLINE: "Offline", NO_DATA: "No data", MAINTENANCE: "Maintenance",
    HEALTHY: "Healthy", DEGRADED: "Degraded", UNAVAILABLE: "Unavailable", NOT_CONFIGURED: "Not configured", UNKNOWN: "Unknown",
    available: "Current", stale: "Stale", missing: "Missing", incomplete: "Incomplete" };
  return h("span", { class: `state state-${state}` }, label[state] || state);
}

export function statusPill(status: string): HTMLElement {
  return h("span", { class: `status status-${status}` }, STATUS_LABEL[status] || status);
}

export function empty(title: string, body?: string, action?: HTMLElement): HTMLElement {
  return h("div", { class: "empty" }, h("p", { class: "empty-title" }, title), body ? h("p", null, body) : null, action || null);
}

export function loading(label = "Loading"): HTMLElement {
  return h("div", { class: "loading", role: "status" }, h("span", { class: "spinner", "aria-hidden": "true" }), label + "…");
}

export function section(title: string | Node, ...children: Child[]): HTMLElement {
  return h("section", { class: "panel" }, h("h2", null, title), ...children);
}

export function kv(rows: [string, Child][]): HTMLElement {
  return h("dl", { class: "kv" }, rows.map(([k, v]) => [h("dt", null, k), h("dd", null, v)]));
}

export function toast(message: string, kind: "ok" | "error" = "ok"): void {
  const host = document.getElementById("toasts");
  if (!host) return;
  const t = h("div", { class: `toast toast-${kind}`, role: kind === "error" ? "alert" : "status" }, message);
  host.appendChild(t);
  setTimeout(() => t.remove(), 5000);
}

// Accessible confirmation dialog built on <dialog>.
export function confirmDialog(opts: { title: string; body: Child; confirm: string; danger?: boolean; form?: HTMLElement; onConfirm: () => Promise<void> }): void {
  const err = h("p", { class: "form-error", role: "alert" });
  const btn = h("button", { class: opts.danger ? "btn btn-danger" : "btn btn-primary", type: "submit" }, opts.confirm);
  const dlg = h("dialog", { class: "dialog" },
    h("form", { method: "dialog", onsubmit: async (e: Event) => {
      e.preventDefault();
      btn.setAttribute("disabled", "");
      err.textContent = "";
      try { await opts.onConfirm(); dlg.close(); dlg.remove(); }
      catch (ex) { err.textContent = (ex as Error).message; btn.removeAttribute("disabled"); }
    } },
      h("h2", null, opts.title), h("div", { class: "dialog-body" }, opts.body), opts.form || null, err,
      h("div", { class: "dialog-actions" },
        h("button", { class: "btn", type: "button", onclick: () => { dlg.close(); dlg.remove(); } }, "Cancel"), btn)));
  // Escape closes a native <dialog> without our handlers running; remove it on any close so stale
  // dialogs (and their duplicate form fields) never accumulate in the page (HDEWS-028).
  dlg.addEventListener("close", () => dlg.remove());
  document.body.appendChild(dlg);
  dlg.showModal();
  const first = dlg.querySelector<HTMLElement>("textarea, input, select");
  (first || btn).focus();
}

export function render(root: Element, ...children: Child[]): void {
  clear(root);
  append(root, children);
}

// Only http(s) links from data are rendered as links; anything else (e.g. javascript:) is not (HDEWS-022).
export function safeUrl(url: string | null | undefined): string | null {
  if (!url) return null;
  try {
    const u = new URL(url, location.href);
    return u.protocol === "https:" || u.protocol === "http:" ? u.href : null;
  } catch { return null; }
}
