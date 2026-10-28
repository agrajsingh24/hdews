// Shared page-level components built on dom.ts.
import { h, riskChip, originTag, HAZARD, when, fmtNum, statePill } from "./dom.js";

export function pageHead(title: string, sub?: (Node | string | null)[] | string | null, actions?: (HTMLElement | null)[]): HTMLElement {
  return h("header", { class: "page-head" },
    h("div", null, h("h1", null, title), sub ? h("p", { class: "page-sub" }, ...(Array.isArray(sub) ? sub : [sub])) : null),
    actions && actions.length ? h("div", { class: "page-actions" }, ...actions) : null);
}

export function errorBox(err: unknown, retry?: () => void): HTMLElement {
  const e = err as { status?: number; message?: string };
  const title = e.status === 403 ? "You don't have access to this" : e.status === 0 ? "Server unreachable" : "Couldn't load this view";
  return h("div", { class: "error-box", role: "alert" },
    h("p", { class: "empty-title" }, title), h("p", null, e.message || String(err)),
    retry ? h("button", { class: "btn", type: "button", onclick: retry }, "Try again") : null);
}

const LEVEL_LABEL: Record<string, string> = { normal: "Normal", watch: "Watch", high: "High", unknown: "Unknown" };

// The evidence-first risk card: what, where, why, how fresh, what is missing, what to do next.
export function assessmentCard(a: any, opts: { explain?: (id: string) => Promise<any>; showSite?: boolean } = {}): HTMLElement {
  if (!a) return h("div", { class: "card" }, h("p", { class: "muted" }, "No assessment yet."));
  const explainHost = h("div", { class: "explain" });
  const factorRows = a.factors.map((f: any) => h("tr", { class: f.points > 0 ? "contrib" : "" },
    h("th", { scope: "row" }, f.label, f.critical ? h("span", { class: "crit", title: "Critical input: without it the tier cannot be confirmed" }, " critical") : null),
    h("td", { class: "num" }, f.value === null ? "—" : fmtNum(f.value, f.unit)),
    h("td", null, h("span", { class: `level level-${f.level}` }, LEVEL_LABEL[f.level] || f.level), f.points ? h("span", { class: "muted" }, ` +${f.points}`) : null),
    h("td", null, statePill(f.status)),
    h("td", { class: "small" }, f.threshold),
    h("td", { class: "small" }, f.as_of ? when(f.as_of) : "—")));
  return h("article", { class: `card assess assess-${a.risk_tier}` },
    h("header", { class: "assess-head" },
      h("div", null,
        h("h3", null, opts.showSite ? `${a.site_name} — ${HAZARD[a.hazard]}` : a.hazard_label),
        h("p", { class: "muted small" }, "Assessed ", when(a.assessed_at), ` · ${a.rule_version}`)),
      h("div", { class: "assess-badges" }, riskChip(a.risk_tier, a.reliability, { lowerBound: a.tier_is_lower_bound }), originTag(a.data_origin))),
    h("p", { class: "assess-summary" }, a.summary),
    a.tier_is_lower_bound ? h("p", { class: "callout callout-warn" },
      `Some inputs are missing or incomplete, so this may understate the risk. With the missing inputs at their worst, the tier could reach ${a.max_possible_tier.toLowerCase()}.`) : null,
    h("div", { class: "table-scroll" }, h("table", { class: "factors" },
      h("caption", { class: "sr-only" }, "Indicators used in this assessment"),
      h("thead", null, h("tr", null, h("th", null, "Indicator"), h("th", null, "Value"), h("th", null, "Level"), h("th", null, "Data"), h("th", null, "Demo threshold"), h("th", null, "As of"))),
      h("tbody", null, factorRows))),
    a.reliability_notes?.length ? h("div", { class: "notes" }, h("h4", null, "Data reliability notes"), h("ul", null, a.reliability_notes.map((n: string) => h("li", null, n)))) : null,
    h("div", { class: "assess-grid" },
      h("div", null, h("h4", null, "What changed"), h("ul", null, (a.changes?.items || []).map((i: string) => h("li", null, i)))),
      h("div", null, h("h4", null, "Review steps (demo playbook, not an approved SOP)"), h("ol", null, a.review_steps.map((st: string) => h("li", null, st))))),
    h("footer", { class: "assess-foot" },
      h("span", { class: "muted small" }, `Score ${a.score} — ${a.score_note} Evidence: ${a.evidence_observation_ids.length} observations.`),
      h("a", { class: "btn btn-small", href: `#/assessments/${a.id}` }, "Inspect evidence"),
      opts.explain ? h("button", { class: "btn btn-small", type: "button", onclick: async (e: Event) => {
        const b = e.currentTarget as HTMLButtonElement;
        b.disabled = true; explainHost.textContent = "Generating explanation…";
        try {
          const x = await opts.explain!(a.id);
          explainHost.replaceChildren(
            h("p", { class: "explain-text" }, ...x.text.split("\n").map((l: string, i: number) => [i ? h("br") : null, l])),
            h("p", { class: "muted small" }, `${x.method === "llm" ? "LLM explanation" : "Template explanation"}. ${x.disclaimer} ${x.llm_note || ""}`));
        } catch (err) { explainHost.textContent = (err as Error).message; }
        b.disabled = false;
      } }, "Explain in plain language") : null),
    explainHost);
}

export function sensorCard(sn: any): HTMLElement {
  const hl = sn.health || {};
  const unit = sn.unit;
  return h("div", { class: `sensor sensor-${hl.state}` },
    h("div", { class: "sensor-top" }, h("strong", null, sn.label), statePill(hl.state || "NO_DATA")),
    h("div", { class: "sensor-value" }, hl.latest_value === null || hl.latest_value === undefined ? "—" : fmtNum(hl.latest_value), h("span", { class: "unit" }, ` ${unit}`),
      hl.state === "STALE" || hl.state === "OFFLINE" ? h("span", { class: "stale-flag" }, " not current") : null),
    h("dl", { class: "sensor-meta" },
      h("dt", null, "Observed"), h("dd", null, when(hl.last_observed_at)),
      h("dt", null, "Received"), h("dd", null, when(hl.last_received_at), hl.delayed ? h("span", { class: "warn-text" }, ` (${Math.round((hl.delay_s || 0) / 60)} min late)`) : null),
      h("dt", null, "Quality"), h("dd", null, hl.latest_quality || "—"),
      h("dt", null, "Source"), h("dd", null, sn.source?.name || sn.source_id, " ", originTag(sn.source?.origin))),
    h("p", { class: "muted small" }, `${sn.id} · reports every ${Math.round(sn.expected_interval_s / 60)} min`));
}
