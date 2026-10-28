import { api, can, getSession } from "../api.js";
import { render, h, originTag, when, ago, HAZARD, statePill, empty, toast, dateOnly, kv, s } from "../dom.js";
import { createMap } from "../map.js";
import { pageHead } from "../ui.js";

// ---------------------------------------------------------------- incidents
export async function incidentsPage(root: HTMLElement, params: URLSearchParams): Promise<void> {
  const q = new URLSearchParams();
  for (const k of ["q", "hazard", "origin", "from", "to"]) if (params.get(k)) q.set(k, params.get(k)!);
  q.set("limit", "100");
  const [data, layers] = await Promise.all([api(`/api/incidents?${q}`), api("/api/map/layers")]);
  const detail = h("aside", { class: "panel incident-detail", "aria-live": "polite" });
  const showDetail = async (id: string) => {
    detail.replaceChildren(h("p", { class: "muted" }, "Loading…"));
    const d = await api(`/api/incidents/${id}`);
    const i = d.incident;
    detail.replaceChildren(
      h("h2", null, i.title),
      h("p", null, originTag(i.origin), " ", h("span", { class: `state state-${i.verification_status}` }, i.verification_status.replace(/_/g, " ").toLowerCase())),
      h("p", null, i.description),
      kv([["Hazard", HAZARD[i.hazard] || i.hazard], ["Date", `${dateOnly(i.event_date)} (precision: ${i.date_precision})`],
        ["Location", `${i.location_name} — ${i.latitude.toFixed(3)}°N ${i.longitude.toFixed(3)}°E (${i.location_precision})`],
        ["Source", i.source_url ? h("a", { href: i.source_url, target: "_blank", rel: "noopener noreferrer" }, i.source_name) : i.source_name],
        ["Notes", i.notes || "—"],
        ["Nearest sites", h("span", null, d.nearby_sites.map((n: any, k: number) => [k ? ", " : "", h("a", { href: `#/sites/${n.id}` }, n.name), ` (${n.distance_km} km)`]))]]),
      h("h3", null, "Associated observations"),
      d.associated_observations.length ? h("p", null, `${d.associated_observations.length} observations recorded at the related site on this date.`)
        : h("p", { class: "muted small" }, d.associated_observations_note));
  };
  const form = h("form", { class: "filters", onsubmit: (e: Event) => {
    e.preventDefault();
    const fd = new FormData(e.target as HTMLFormElement);
    const p = new URLSearchParams();
    for (const [k, v] of fd.entries()) if (v) p.set(k, String(v));
    location.hash = `#/incidents?${p}`;
  } },
    h("label", null, h("span", null, "Search"), h("input", { name: "q", type: "search", value: params.get("q") || "", placeholder: "Place or keyword" })),
    h("label", null, h("span", null, "Hazard"), h("select", { name: "hazard" }, h("option", { value: "" }, "Any"),
      ...["landslide", "flash_flood"].map(x => h("option", { value: x, selected: params.get("hazard") === x }, HAZARD[x])))),
    h("label", null, h("span", null, "Record type"), h("select", { name: "origin" }, h("option", { value: "" }, "Any"),
      h("option", { value: "IMPORTED", selected: params.get("origin") === "IMPORTED" }, "Public reports"),
      h("option", { value: "SYNTHETIC", selected: params.get("origin") === "SYNTHETIC" }, "Synthetic demo records"))),
    h("label", null, h("span", null, "From"), h("input", { name: "from", type: "date", value: params.get("from") || "" })),
    h("label", null, h("span", null, "To"), h("input", { name: "to", type: "date", value: params.get("to") || "" })),
    h("button", { class: "btn btn-primary", type: "submit" }, "Apply filters"),
    h("a", { class: "btn", href: "#/incidents" }, "Clear"));

  // timeline strip by year
  const years = data.items.map((i: any) => Number(i.event_date.slice(0, 4)));
  const minY = Math.min(2012, ...years), maxY = Math.max(2026, ...years);
  const W = 640, H = 64;
  const tl = s("svg", { viewBox: `0 0 ${W} ${H}`, class: "timeline-svg", role: "img", "aria-label": "Incidents by year" });
  for (let y = minY; y <= maxY; y++) {
    const x = 20 + (y - minY) / (maxY - minY) * (W - 40);
    tl.appendChild(s("line", { x1: x, x2: x, y1: 40, y2: 44, class: "tick" }));
    if ((y - minY) % 2 === 0) tl.appendChild(s("text", { x, y: 58, class: "axis", "text-anchor": "middle" }, String(y)));
  }
  tl.appendChild(s("line", { x1: 20, x2: W - 20, y1: 40, y2: 40, class: "grid" }));
  const stack: Record<number, number> = {};
  for (const i of data.items) {
    const d = new Date(i.event_date + "T00:00:00Z");
    const fy = d.getUTCFullYear() + d.getUTCMonth() / 12;
    const x = 20 + (fy - minY) / (maxY - minY) * (W - 40);
    const k = Math.round(x / 8);
    stack[k] = (stack[k] || 0) + 1;
    const c = s("circle", { cx: x, cy: 40 - stack[k] * 9, r: 4, class: `tl-dot tl-${i.origin}` });
    c.appendChild(s("title", {}, `${i.title} (${i.event_date})`));
    tl.appendChild(c);
  }

  const m = createMap({ data: layers, layers: { sites: true, rivers: true, incidents: true, hazard_zones: false, places: true }, tiles: false, height: 340 });
  render(root, 
    pageHead("Historical incidents", "Public reports are summaries with source links, not yet cross-checked against an official inventory. Synthetic records are fabricated for the demo and describe no real event."),
    form,
    h("div", { class: "incident-layout" },
      h("div", null,
        h("figure", { class: "chart-wrap" }, h("figcaption", null, h("strong", null, "Timeline"), h("span", { class: "muted" }, " filled = public report, hollow = synthetic")), tl),
        data.items.length ? h("div", { class: "table-scroll" }, h("table", null,
          h("thead", null, h("tr", null, ...["Date", "Incident", "Hazard", "Location", "Record"].map(t => h("th", null, t)))),
          h("tbody", null, data.items.map((i: any) => h("tr", null,
            h("td", { class: "nowrap" }, dateOnly(i.event_date)),
            h("td", null, h("button", { class: "linkish", type: "button", onclick: () => showDetail(i.id) }, i.title)),
            h("td", null, HAZARD[i.hazard] || i.hazard), h("td", { class: "small" }, i.location_name), h("td", null, originTag(i.origin)))))))
          : empty("No incidents match these filters.", "Clear the filters to see all records.")),
      h("div", null, detail, m.el)));
  const pick = params.get("id") || data.items[0]?.id;
  if (pick) showDetail(pick).catch(() => {});
  else detail.replaceChildren(empty("Select an incident to see details."));
}

// ------------------------------------------------------------- data sources
export async function sourcesPage(root: HTMLElement): Promise<void> {
  const d = await api("/api/data-sources");
  render(root, 
    pageHead("Data sources", ["Registry of configured and candidate sources. Health is derived from data actually received. Checked ", when(d.generated_at), "."]),
    h("div", { class: "source-list" }, d.items.map((src: any) => h("article", { class: `card source source-${src.health_status}` },
      h("header", { class: "source-head" }, h("h2", null, src.name), statePill(src.health_status)),
      h("p", null, originTag(src.origin), h("span", { class: "muted small" }, ` ${src.id}, ${src.source_type.replace(/_/g, " ")}, ${src.access_mode.replace(/_/g, " ")}`)),
      h("p", { class: "small" }, src.description),
      kv([["Last successful update", src.last_success_at ? h("span", null, when(src.last_success_at), ` (${ago(src.last_success_at)})`) : "never"],
        ["Observations stored", String(src.observation_count)], ["Sensors", String(src.sensor_count)],
        ["Update cadence", src.update_cadence || "—"], ["Attribution", src.attribution || "—"], ["Licence / terms", src.licence || "—"],
        ["Last error", src.last_error ? h("span", { class: "form-error" }, src.last_error, " ", when(src.last_error_at)) : "none recorded"],
        ["Reference", src.url ? h("a", { href: src.url, target: "_blank", rel: "noopener noreferrer" }, "documentation") : "—"]])))));
}

// --------------------------------------------------------------- evaluation
export async function evaluationPage(root: HTMLElement): Promise<void> {
  const e = await api("/api/evaluation");
  const rules = await api("/api/rules");
  render(root, 
    pageHead("Model and evaluation", "What has and has not been measured."),
    e.status === "NOT_EVALUATED"
      ? h("section", { class: "not-evaluated", role: "status" }, h("h2", null, "Not evaluated yet"), h("p", null, e.message))
      : h("section", { class: "panel" }, h("h2", null, "Evaluation runs"), e.runs.map((r: any) => h("article", { class: "card" },
          h("h3", null, `${r.model_name} ${r.model_version}`),
          kv([["Dataset", `${r.dataset_name} ${r.dataset_version}`], ["Split", r.split_strategy], ["Train period", r.train_period],
            ["Test period", r.test_period], ["Regions", r.regions.join(", ")], ["Test events / non-events", `${r.n_test_events} / ${r.n_test_negatives}`],
            ["Calibrated probabilities", r.calibrated ? "yes" : "no — scores are not probabilities"]]),
          h("table", { class: "compact" }, h("tbody", null, Object.entries(r.metrics).map(([k, v]) => h("tr", null, h("th", null, k), h("td", { class: "num" }, v === null ? "not measurable" : String(v)))))),
          h("p", { class: "small" }, r.limitations)))),
    h("div", { class: "two-col" },
      h("section", { class: "panel" }, h("h2", null, "Current method"),
        kv([["Engine", "Baseline rules (transparent, deterministic)"], ["Rule version", rules.rule_version], ["Thresholds", "Uncalibrated demonstration settings"],
          ["ML model", "None registered. The interface refuses models that are not validated on labelled data."],
          ["LLM", "Explanations only; never computes risk. Output that cites numbers absent from the evidence is discarded."]]),
        h("h3", null, "How a tier is decided"), h("ol", null, rules.tier_logic.map((t: string) => h("li", null, t)))),
      h("section", { class: "panel" }, h("h2", null, "What an evaluation needs"),
        h("ul", null, e.requirements.map((r: string) => h("li", null, r))),
        h("h3", null, "Metrics that will be reported"), h("ul", null, e.metrics_reported_when_available.map((r: string) => h("li", null, r))),
        h("p", { class: "small" }, "Run: ", h("code", null, e.how_to_run)))),
    h("section", { class: "panel" }, h("h2", null, "Indicators and demo points"),
      Object.entries(rules.indicators).map(([hz, list]: [string, any]) => h("div", null, h("h3", null, HAZARD[hz]),
        h("div", { class: "table-scroll" }, h("table", { class: "compact" },
          h("thead", null, h("tr", null, ...["Indicator", "Critical", "Watch pts", "High pts", "Default demo threshold"].map(t => h("th", null, t)))),
          h("tbody", null, list.map((r: any) => h("tr", null, h("td", null, r.key), h("td", null, r.critical ? "yes" : "no"),
            h("td", { class: "num" }, String(r.watch_points)), h("td", { class: "num" }, String(r.high_points)), h("td", { class: "small" }, r.threshold))))))))));
}

// ---------------------------------------------------------------- audit log
export async function auditPage(root: HTMLElement, params: URLSearchParams): Promise<void> {
  const offset = Number(params.get("offset") || 0), limit = 50;
  const q = new URLSearchParams({ limit: String(limit), offset: String(offset) });
  for (const k of ["entity_id", "event_prefix", "entity_type"]) if (params.get(k)) q.set(k, params.get(k)!);
  const d = await api(`/api/audit-log?${q}`);
  const verifyOut = h("span", { class: "small", "aria-live": "polite" });
  const link = (over: Record<string, string>) => {
    const p = new URLSearchParams(params); for (const [k, v] of Object.entries(over)) v ? p.set(k, v) : p.delete(k);
    return `#/audit?${p}`;
  };
  const summarize = (ev: any) => {
    const x = ev.details;
    if (ev.event_type.startsWith("alert.")) return [x.from && x.to ? `${x.from} → ${x.to}` : "", x.notes || x.reason || x.note || ""].filter(Boolean).join(". ");
    if (ev.event_type === "assessment.changed") return `${HAZARD[x.hazard]}: ${x.previous_tier || "—"} → ${x.risk_tier} (reliability ${x.reliability.toLowerCase()}, ${x.trigger})`;
    if (ev.event_type === "simulation.scenario_applied") return `${x.name} on ${x.site_ids.join(", ")}`;
    return Object.entries(x).filter(([, v]) => typeof v !== "object").map(([k, v]) => `${k}: ${v}`).join(", ").slice(0, 160);
  };
  render(root, 
    pageHead("Audit log", "Append-only. Each event is chained to the previous one with a SHA-256 hash, and the database rejects edits and deletions.",
      [h("button", { class: "btn", type: "button", onclick: async () => {
        verifyOut.textContent = "Verifying…";
        const v = await api("/api/audit-log/verify");
        verifyOut.textContent = v.valid ? `Chain intact: ${v.events_checked} events verified.` : `Chain broken at event #${v.broken_at_seq}.`;
        verifyOut.className = v.valid ? "small ok-text" : "small form-error";
      } }, "Verify hash chain"), verifyOut]),
    h("nav", { class: "tabs", "aria-label": "Event filter" }, ...[["", "All"], ["alert.", "Alerts"], ["assessment.", "Assessments"], ["simulation.", "Simulation"], ["auth.", "Sign-ins"], ["ingestion.", "Ingestion"], ["site.", "Configuration"]]
      .map(([k, l]) => h("a", { href: link({ event_prefix: k, offset: "" }), class: (params.get("event_prefix") || "") === k ? "active" : "" }, l))),
    params.get("entity_id") ? h("p", { class: "small" }, `Filtered to ${params.get("entity_id")}. `, h("a", { href: link({ entity_id: "" }) }, "Clear filter")) : null,
    d.items.length ? h("div", { class: "table-scroll" }, h("table", { class: "compact audit" },
      h("thead", null, h("tr", null, ...["#", "Time", "Actor", "Event", "Entity", "Details", "Hash"].map(t => h("th", null, t)))),
      h("tbody", null, d.items.map((ev: any) => h("tr", null, h("td", { class: "num" }, String(ev.seq)), h("td", { class: "nowrap" }, when(ev.occurred_at)),
        h("td", null, ev.actor_name, h("div", { class: "muted small" }, ev.actor_role)), h("td", null, h("code", null, ev.event_type)),
        h("td", { class: "small" }, ev.entity_type === "alert" ? h("a", { href: `#/alerts/${ev.entity_id}` }, ev.entity_id) :
          ev.entity_type === "site" ? h("a", { href: `#/sites/${ev.entity_id}` }, ev.entity_id) : `${ev.entity_type} ${ev.entity_id || ""}`),
        h("td", { class: "small" }, summarize(ev)), h("td", { class: "hash small", title: ev.hash }, ev.hash.slice(0, 10) + "…")))))) : empty("No audit events match."),
    h("div", { class: "pager" }, h("span", { class: "muted small" }, `${d.total} events`),
      offset > 0 ? h("a", { class: "btn btn-small", href: link({ offset: String(Math.max(0, offset - limit)) }) }, "Newer") : null,
      d.has_more ? h("a", { class: "btn btn-small", href: link({ offset: String(offset + limit) }) }, "Older") : null));
}

// ----------------------------------------------------------------- settings
export async function settingsPage(root: HTMLElement): Promise<void> {
  const [meta, sites] = await Promise.all([api("/api/meta"), api("/api/sites")]);
  const sess = getSession()!;
  const admin = can("manage_config");
  const siteSel = h("select", { "aria-label": "Site" }, sites.items.map((x: any) => h("option", { value: x.id }, `${x.name} (${x.id})`)));
  const area = h("textarea", { rows: 12, class: "code", spellcheck: "false", disabled: !admin, "aria-label": "Site threshold overrides (JSON)" });
  const eff = h("pre", { class: "code small" });
  const out = h("p", { class: "small", role: "status" });
  const load = async () => {
    const d = await api(`/api/sites/${siteSel.value}`);
    area.value = JSON.stringify(d.site.config, null, 2);
    eff.textContent = JSON.stringify({ landslide: d.effective_config.landslide, flash_flood: d.effective_config.flash_flood }, null, 2);
    out.textContent = "";
  };
  siteSel.addEventListener("change", load);
  const save = h("button", { class: "btn btn-primary", type: "button", disabled: !admin, onclick: async () => {
    let overrides: unknown;
    try { overrides = JSON.parse(area.value || "{}"); } catch { out.className = "small form-error"; out.textContent = "Overrides must be valid JSON."; return; }
    try {
      await api(`/api/sites/${siteSel.value}/config`, { method: "PUT", body: { overrides } });
      toast("Thresholds saved and the site re-assessed."); await load(); out.className = "small ok-text"; out.textContent = "Saved. The change is in the audit log.";
    } catch (err) { out.className = "small form-error"; out.textContent = (err as Error).message; }
  } }, "Save thresholds");
  render(root, 
    pageHead("Settings"),
    h("div", { class: "two-col" },
      h("section", { class: "panel" }, h("h2", null, "Your session"),
        kv([["Name", sess.user.display_name], ["Role", sess.user.role], ["Permissions", sess.permissions.join(", ")]]),
        h("p", { class: "muted small" }, "Demo accounts only. Replace with your organisation's identity provider before any real use.")),
      h("section", { class: "panel" }, h("h2", null, "System"),
        kv([["Environment", meta.environment], ["Demo endpoints", meta.demo_endpoints ? "enabled (simulator available)" : "disabled"],
          ["Rule version", meta.rule_version], ["Threshold status", meta.threshold_status], ["Playbook", meta.playbook_version],
          ["Explanation provider", meta.llm_provider === "none" ? "Template (no LLM configured)" : meta.llm_provider], ["Server time", when(meta.server_time)]]))),
    h("section", { class: "panel" }, h("h2", null, "Site thresholds"),
      h("p", { class: "small" }, "Site-specific overrides merged over the defaults. These remain uncalibrated demonstration settings; watch values must be lower than high values. ",
        admin ? "Saving re-runs the site's assessment." : "Only administrators can edit."),
      h("div", { class: "toolbar" }, siteSel),
      h("div", { class: "two-col" }, h("div", null, h("h3", null, "Overrides (JSON)"), area, h("div", { class: "toolbar" }, save), out),
        h("div", null, h("h3", null, "Effective hazard thresholds"), eff))));
  await load();
}
