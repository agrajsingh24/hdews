import { api, can } from "../api.js";
import { render, h, riskChip, originTag, when, ago, HAZARD, statusPill, fmtNum, empty, toast, confirmDialog, kv, STATUS_LABEL } from "../dom.js";
import { pageHead, assessmentCard } from "../ui.js";
const explain = (id) => api(`/api/assessments/${id}/explanation`);
export async function alertsPage(root, params) {
    const status = params.get("status") || "open";
    const kind = params.get("kind") || "";
    const offset = Number(params.get("offset") || 0);
    const limit = 25;
    const q = new URLSearchParams({ status, limit: String(limit), offset: String(offset) });
    if (kind)
        q.set("kind", kind);
    const data = await api(`/api/alerts?${q}`);
    const link = (over) => {
        const p = new URLSearchParams({ status, kind, offset: "0", ...over });
        [...p.keys()].forEach(k => { if (!p.get(k))
            p.delete(k); });
        return `#/alerts?${p}`;
    };
    const tabs = h("nav", { class: "tabs", "aria-label": "Alert status" }, ...[["open", "Open"], ["REVIEW_REQUIRED", "Awaiting review"], ["resolved", "Resolved"], ["all", "All"]].map(([k, l]) => h("a", { href: link({ status: k }), class: k === status ? "active" : "", "aria-current": k === status ? "page" : undefined }, l)));
    const kindSel = h("select", { "aria-label": "Alert kind", onchange: (e) => { location.hash = link({ kind: e.target.value }); } }, h("option", { value: "", selected: !kind }, "All kinds"), h("option", { value: "HAZARD", selected: kind === "HAZARD" }, "Hazard"), h("option", { value: "DATA_QUALITY", selected: kind === "DATA_QUALITY" }, "Data gap"));
    render(root, pageHead("Candidate alerts", "Generated when an assessment meets the demo alert criteria. Each one needs review by an authorised reviewer; none is an official warning and nothing is sent to the public."), h("div", { class: "toolbar" }, tabs, kindSel), data.items.length ? h("div", { class: "table-scroll" }, h("table", { class: "alerts-table" }, h("thead", null, h("tr", null, ...["Alert", "Site", "Severity", "Status", "Raised", "Updated", "Evidence"].map(t => h("th", null, t)))), h("tbody", null, data.items.map((a) => h("tr", { class: a.status === "REVIEW_REQUIRED" ? "row-attn" : "" }, h("td", null, h("span", { class: `kind kind-${a.kind}` }, a.kind === "HAZARD" ? "Hazard" : "Data gap"), " ", h("a", { href: `#/alerts/${a.id}` }, a.title)), h("td", null, h("a", { href: `#/sites/${a.site_id}` }, a.site_name), h("div", { class: "muted small" }, HAZARD[a.hazard])), h("td", null, a.kind === "HAZARD" ? riskChip(a.severity, undefined, { compact: true }) : h("span", { class: "muted" }, "Data gap")), h("td", null, statusPill(a.status)), h("td", null, when(a.created_at)), h("td", { class: "small" }, ago(a.updated_at), a.trigger_count > 1 ? h("div", { class: "muted" }, `condition seen ${a.trigger_count}×`) : null), h("td", null, originTag(a.data_origin)))))))
        : empty(status === "open" ? "No open candidate alerts" : "No alerts match this filter", status === "open" ? "Alerts appear here when a site's assessment reaches the demo criteria. Use the simulator to create one." : undefined, can("run_scenario") && status === "open" ? h("a", { class: "btn btn-primary", href: "#/simulator" }, "Open the simulator") : undefined), h("div", { class: "pager" }, h("span", { class: "muted small" }, `${data.total} alert${data.total === 1 ? "" : "s"}`), offset > 0 ? h("a", { class: "btn btn-small", href: link({ offset: String(Math.max(0, offset - limit)) }) }, "Previous") : null, data.has_more ? h("a", { class: "btn btn-small", href: link({ offset: String(offset + limit) }) }, "Next") : null));
}
const STEPS = ["REVIEW_REQUIRED", "ACKNOWLEDGED", "ACTION_ASSIGNED", "RESOLVED"];
const ACTION_LABEL = {
    acknowledge: "Acknowledged", field_verification: "Field verification assigned", escalation: "Escalated",
    test_notification: "Demo test notification recorded", note: "Note", resolve: "Resolved",
};
function textarea(name, label, required = true, placeholder = "") {
    return h("label", { class: "field" }, h("span", null, label), h("textarea", { name, rows: 3, required, minlength: required ? 3 : undefined, placeholder }));
}
export async function alertPage(root, id) {
    const d = await api(`/api/alerts/${id}`);
    const a = d.alert;
    const reload = () => alertPage(root, id);
    const isOpen = a.status !== "RESOLVED";
    const mayReview = can("alert_review");
    const run = async (path, body, done) => {
        await api(`/api/alerts/${id}/${path}`, { method: "POST", body });
        toast(done);
        await reload();
    };
    const formValue = (dlgForm, name) => dlgForm.querySelector(`[name=${name}]`).value;
    const ackBtn = h("button", { class: "btn btn-primary", type: "button", onclick: () => {
            const form = h("div", null, textarea("notes", "Note (optional)", false, "e.g. Reviewing rainfall and displacement evidence"));
            confirmDialog({ title: "Acknowledge this alert?", confirm: "Acknowledge", form,
                body: h("p", null, "This records that you have taken ownership of the review. It does not issue any warning."),
                onConfirm: () => run("acknowledge", { notes: formValue(form, "notes") }, "Alert acknowledged.") });
        } }, "Acknowledge");
    const actionBtn = h("button", { class: "btn", type: "button", onclick: () => {
            const form = h("div", null, h("label", { class: "field" }, h("span", null, "Action"), h("select", { name: "action_type" }, h("option", { value: "field_verification" }, "Request field verification"), h("option", { value: "escalation" }, "Escalate to duty officer"), h("option", { value: "test_notification" }, "Record a demo test notification (nothing is sent)"), h("option", { value: "note" }, "Add a note only"))), h("label", { class: "field" }, h("span", null, "Assigned to (team or role)"), h("input", { name: "assignee", type: "text", maxlength: 120, placeholder: "e.g. Field team 2" })), textarea("notes", "Details", true, "What should be done, and why"));
            confirmDialog({ title: "Record an action", confirm: "Record action", form,
                body: h("p", null, "Recorded in the alert history and audit log. HDEWS does not contact anyone."),
                onConfirm: () => run("actions", { action_type: formValue(form, "action_type"), assignee: formValue(form, "assignee") || null, notes: formValue(form, "notes") }, "Action recorded.") });
        } }, "Record action");
    const resolveBtn = h("button", { class: "btn", type: "button", onclick: () => {
            const form = h("div", null, h("label", { class: "field" }, h("span", null, "Outcome"), h("select", { name: "category" }, h("option", { value: "exercise" }, "Exercise or demonstration"), h("option", { value: "condition_cleared" }, "Condition cleared"), h("option", { value: "false_alarm" }, "False alarm"), h("option", { value: "data_issue" }, "Data issue"), h("option", { value: "confirmed_event" }, "Confirmed event"))), textarea("reason", "Reason", true, "Required — this is kept for false-alarm and missed-event review"));
            confirmDialog({ title: "Resolve this alert?", confirm: "Resolve alert", danger: true, form,
                body: h("p", null, "Resolved alerts cannot be reopened. If the condition persists, the next assessment opens a new alert."),
                onConfirm: () => run("resolve", { category: formValue(form, "category"), reason: formValue(form, "reason") }, "Alert resolved.") });
        } }, "Resolve");
    const controls = !isOpen ? null : !mayReview
        ? h("p", { class: "callout" }, "Only reviewer or administrator roles can act on alerts. You can inspect the evidence.")
        : h("div", { class: "alert-controls" }, a.status === "REVIEW_REQUIRED" ? ackBtn : null, a.status !== "REVIEW_REQUIRED" ? actionBtn : null, a.status !== "REVIEW_REQUIRED" ? resolveBtn : null, a.status === "REVIEW_REQUIRED" ? h("span", { class: "muted small" }, "Acknowledge first; actions and resolution unlock after that.") : null);
    const stepIdx = STEPS.indexOf(a.status);
    const stepper = h("ol", { class: "stepper", "aria-label": "Review progress" }, STEPS.map((st, i) => h("li", { class: i < stepIdx ? "done" : i === stepIdx ? "current" : "", "aria-current": i === stepIdx ? "step" : undefined }, STATUS_LABEL[st])));
    const cur = d.current_assessment;
    const trig = d.triggering_assessment;
    const currentNote = cur && cur.id !== trig.id ? h("p", { class: `callout${cur.risk_tier === trig.risk_tier ? "" : " callout-warn"}` }, "Latest assessment for this site (", when(cur.assessed_at), "): ", riskChip(cur.risk_tier, cur.reliability, { compact: true }), " ", cur.summary) : null;
    render(root, h("div", { class: "demo-notice", role: "note" }, h("strong", null, "Not an official warning. "), "Demo candidate alert for authorised review only. No message has been sent to anyone."), pageHead(a.title, [h("a", { href: `#/sites/${a.site_id}` }, d.site.name), `, ${HAZARD[a.hazard]}. Raised `, when(a.created_at), `. `, originTag(a.data_origin)], [h("a", { class: "btn", href: "#/alerts" }, "All alerts")]), stepper, h("div", { class: "alert-summary" }, kv([["Kind", a.kind === "HAZARD" ? "Hazard condition" : "Critical data gap during adverse conditions"],
        ["Severity", a.kind === "HAZARD" ? riskChip(a.severity, trig.reliability) : "Data gap"],
        ["Status", statusPill(a.status)],
        ["Last data update", when(trig.sensor_health?.map((s) => s.last_received_at).filter(Boolean).sort().pop())],
        ["Condition re-confirmed", `${a.trigger_count} assessment${a.trigger_count > 1 ? "s" : ""} (deduplicated into this alert)`],
        ["Acknowledged", a.acknowledged_at ? h("span", null, a.acknowledged_by_name, ", ", when(a.acknowledged_at)) : "—"],
        ["Resolved", a.resolved_at ? h("span", null, a.resolved_by_name, ", ", when(a.resolved_at), ` — ${a.resolution_category.replace(/_/g, " ")}: ${a.resolution_reason}`) : "—"]]), controls), currentNote, h("h2", { class: "section-title" }, "Evidence behind this alert"), assessmentCard(trig, { explain }), h("section", { class: "panel" }, h("h2", null, `Observations referenced (${d.evidence_observations.length})`), d.evidence_observations.length ? h("details", null, h("summary", null, "Show observation list"), h("div", { class: "table-scroll tall" }, h("table", { class: "compact" }, h("thead", null, h("tr", null, ...["ID", "Sensor", "Value", "Observed", "Received", "Quality", "Origin"].map(t => h("th", null, t)))), h("tbody", null, d.evidence_observations.map((o) => h("tr", null, h("td", { class: "num" }, String(o.id)), h("td", null, o.sensor_id), h("td", { class: "num" }, fmtNum(o.value, o.unit)), h("td", null, when(o.observed_at)), h("td", null, when(o.received_at)), h("td", null, o.quality_status), h("td", null, originTag(o.origin))))))))
        : h("p", { class: "callout callout-warn" }, "The referenced observations are no longer stored (a newer simulated scenario replaced them). The assessment record above keeps the values used.")), h("div", { class: "two-col" }, h("section", { class: "panel" }, h("h2", null, "Action log"), d.actions.length ? h("ol", { class: "timeline" }, d.actions.map((ac) => h("li", null, h("strong", null, ACTION_LABEL[ac.action_type] || ac.action_type), ac.assignee ? ` → ${ac.assignee}` : "", h("div", null, ac.notes), h("div", { class: "muted small" }, `${ac.actor_name} (${ac.actor_role}), `, when(ac.created_at))))) : empty("No actions recorded yet.")), h("section", { class: "panel" }, h("h2", null, "Audit history"), h("ol", { class: "timeline" }, d.history.map((ev) => h("li", null, h("code", null, ev.event_type), " ", h("span", { class: "muted small" }, `#${ev.seq}, ${ev.actor_name}, `, when(ev.occurred_at)), h("div", { class: "muted small hash", title: "SHA-256 chain hash" }, ev.hash.slice(0, 16) + "…")))), h("a", { href: `#/audit?entity_id=${a.id}` }, "Open in audit log"))), h("section", { class: "panel" }, h("h2", null, `Assessments linked to this alert (${d.linked_assessments.length})`), h("ul", { class: "plain small" }, d.linked_assessments.slice(0, 10).map((l) => h("li", null, h("a", { href: `#/assessments/${l.id}` }, l.id), " ", riskChip(l.risk_tier, l.reliability, { compact: true }), " ", when(l.assessed_at))))));
}
