"""Candidate-alert generation and the human review lifecycle.

Lifecycle: REVIEW_REQUIRED → ACKNOWLEDGED → ACTION_ASSIGNED → RESOLVED
(ACKNOWLEDGED → RESOLVED is also allowed). Candidate alerts are internal review
items: nothing in this module sends a message to anyone outside the system.
"""
from __future__ import annotations

import uuid

from .. import clock
from ..db import Tx
from . import audit
from .risk_engine import tier_at_least
from .risk_engine.rules import HAZARD_LABELS

ACTION_TYPES_ASSIGNING = {"field_verification", "escalation", "test_notification"}
ACTION_TYPES = ACTION_TYPES_ASSIGNING | {"note"}
RESOLUTION_CATEGORIES = ("condition_cleared", "false_alarm", "confirmed_event", "data_issue", "exercise")


class TransitionError(Exception):
    """Raised for an alert action that is not valid in the alert's current state."""


def _open_alert(tx: Tx, dedup_key: str) -> dict | None:
    return tx.one("SELECT * FROM alerts WHERE dedup_key = ? AND status <> 'RESOLVED'", (dedup_key,))


def process_assessment(tx: Tx, site: dict, result: dict, cfg: dict, actor: dict | None = None) -> dict | None:
    """Create or update candidate alerts for one assessment. Returns the alert touched, if any."""
    hazard = result["hazard"]
    touched = None
    min_tier = cfg["alerting"]["hazard_alert_min_tier"]
    if tier_at_least(result["risk_tier"], min_tier):
        touched = _upsert(tx, site, result, "HAZARD", result["risk_tier"],
                          f"{HAZARD_LABELS[hazard]} — {result['risk_tier']} at {site['name']}", actor)
    rain_1h = result.get("observed_rain_1h_mm")
    adverse = (rain_1h is not None and rain_1h >= cfg["alerting"]["data_quality_alert_rain_1h_mm"]) or \
        tier_at_least(result["computed_tier_from_available_evidence"], "ELEVATED")
    # HDEWS-036: if the site's own rain gauge is down, adverse weather cannot be ruled out. Requiring
    # observed rain as proof meant a complete blackout (often caused by the storm) raised nothing.
    # Sites with no rain gauge configured are excluded: that is a design limit, not an outage.
    rain_factor = next((f for f in result.get("factors", []) if f["key"] == "rain_1h_mm"), None)
    gauge_configured = any(h.get("sensor_type") == "rain_gauge" for h in result.get("sensor_health", []))
    weather_unknown = gauge_configured and rain_factor is not None and rain_factor["status"] in ("missing", "stale")
    if result["reliability"] == "POOR" and (adverse or weather_unknown):
        missing = ", ".join(m["label"].lower() for m in result["missing_inputs"] if m["critical"])
        condition = "during adverse conditions" if adverse else "while adverse weather cannot be ruled out (rain gauge unavailable)"
        _upsert(tx, site, result, "DATA_QUALITY", "DATA_GAP",
                f"Critical data gap {condition} — {missing} ({HAZARD_LABELS[hazard].lower()}) at {site['name']}",
                actor)
    return touched


def _upsert(tx: Tx, site: dict, result: dict, kind: str, severity: str, title: str, actor: dict | None) -> dict:
    dedup_key = f"{site['id']}:{result['hazard']}:{kind}"
    now = clock.now_iso()
    existing = _open_alert(tx, dedup_key)
    if existing:
        # Deduplicate: link the new assessment to the open alert instead of creating another one.
        tx.execute("UPDATE alerts SET latest_assessment_id = ?, trigger_count = trigger_count + 1, updated_at = ?, "
                   "severity = ?, data_origin = ? WHERE id = ?",
                   (result["id"], now, severity, result["data_origin"], existing["id"]))
        tx.insert("alert_assessments", {"alert_id": existing["id"], "assessment_id": result["id"], "linked_at": now})
        if existing["severity"] != severity:
            audit.record(tx, "alert.severity_changed", "alert", existing["id"],
                         {"from": existing["severity"], "to": severity, "assessment_id": result["id"]}, actor)
        return {**existing, "latest_assessment_id": result["id"]}
    alert_id = "al_" + uuid.uuid4().hex[:12]
    row = {
        "id": alert_id, "site_id": site["id"], "hazard": result["hazard"], "kind": kind, "severity": severity,
        "status": "REVIEW_REQUIRED", "title": title, "data_origin": result["data_origin"], "dedup_key": dedup_key,
        "created_at": now, "updated_at": now, "first_assessment_id": result["id"],
        "latest_assessment_id": result["id"], "trigger_count": 1,
    }
    tx.insert("alerts", row)
    tx.insert("alert_assessments", {"alert_id": alert_id, "assessment_id": result["id"], "linked_at": now})
    audit.record(tx, "alert.created", "alert", alert_id, {
        "kind": kind, "severity": severity, "site_id": site["id"], "hazard": result["hazard"],
        "assessment_id": result["id"], "data_origin": result["data_origin"], "rule_version": result["rule_version"],
        "note": "Candidate alert for human review. Not an official warning; no message sent.",
    }, actor)
    return row


def get(tx: Tx, alert_id: str) -> dict:
    alert = tx.one("SELECT * FROM alerts WHERE id = ?", (alert_id,))
    if not alert:
        raise LookupError(alert_id)
    return alert


def _action(tx: Tx, alert_id: str, actor: dict, action_type: str, notes: str, assignee: str | None = None) -> dict:
    seq = (tx.scalar("SELECT MAX(seq) FROM alert_actions WHERE alert_id = ?", (alert_id,)) or 0) + 1
    row = {"id": "ac_" + uuid.uuid4().hex[:12], "alert_id": alert_id, "actor_id": actor["id"], "seq": seq,
           "action_type": action_type, "assignee": assignee, "notes": notes, "created_at": clock.now_iso()}
    tx.insert("alert_actions", row)
    return row


def acknowledge(tx: Tx, alert_id: str, actor: dict, notes: str = "") -> dict:
    alert = get(tx, alert_id)
    if alert["status"] != "REVIEW_REQUIRED":
        raise TransitionError(f"Only alerts in REVIEW_REQUIRED can be acknowledged (current: {alert['status']}).")
    now = clock.now_iso()
    tx.execute("UPDATE alerts SET status = 'ACKNOWLEDGED', acknowledged_by = ?, acknowledged_at = ?, updated_at = ? "
               "WHERE id = ? AND status = 'REVIEW_REQUIRED'", (actor["id"], now, now, alert_id))
    _action(tx, alert_id, actor, "acknowledge", notes or "Acknowledged; evidence under review.")
    audit.record(tx, "alert.acknowledged", "alert", alert_id, {"from": alert["status"], "to": "ACKNOWLEDGED", "notes": notes}, actor)
    return get(tx, alert_id)


def add_action(tx: Tx, alert_id: str, actor: dict, action_type: str, notes: str, assignee: str | None) -> dict:
    alert = get(tx, alert_id)
    if action_type not in ACTION_TYPES:
        raise TransitionError(f"Unknown action type '{action_type}'.")
    if alert["status"] == "RESOLVED":
        raise TransitionError("Alert is resolved; no further actions can be recorded.")
    if action_type in ACTION_TYPES_ASSIGNING and alert["status"] == "REVIEW_REQUIRED":
        raise TransitionError("Acknowledge the alert before assigning an action.")
    if action_type in ACTION_TYPES_ASSIGNING and not (assignee or "").strip():
        raise TransitionError("An assignee (team or role) is required for this action.")
    if action_type == "test_notification":
        notes = "[DEMO TEST NOTIFICATION — recorded only, nothing was sent] " + notes
    action = _action(tx, alert_id, actor, action_type, notes, assignee)
    new_status = alert["status"]
    if action_type in ACTION_TYPES_ASSIGNING:
        new_status = "ACTION_ASSIGNED"
        tx.execute("UPDATE alerts SET status = ?, updated_at = ? WHERE id = ?", (new_status, clock.now_iso(), alert_id))
    else:
        tx.execute("UPDATE alerts SET updated_at = ? WHERE id = ?", (clock.now_iso(), alert_id))
    audit.record(tx, f"alert.action.{action_type}", "alert", alert_id, {
        "action_id": action["id"], "assignee": assignee, "notes": notes, "from": alert["status"], "to": new_status,
    }, actor)
    return get(tx, alert_id)


def resolve(tx: Tx, alert_id: str, actor: dict, category: str, reason: str) -> dict:
    alert = get(tx, alert_id)
    if alert["status"] == "RESOLVED":
        raise TransitionError("Alert is already resolved.")
    if alert["status"] == "REVIEW_REQUIRED":
        raise TransitionError("Acknowledge the alert before resolving it.")
    if category not in RESOLUTION_CATEGORIES:
        raise TransitionError(f"Resolution category must be one of {', '.join(RESOLUTION_CATEGORIES)}.")
    if len(reason.strip()) < 5:
        raise TransitionError("A resolution reason (at least 5 characters) is required.")
    now = clock.now_iso()
    tx.execute("UPDATE alerts SET status = 'RESOLVED', resolved_by = ?, resolved_at = ?, resolution_category = ?, "
               "resolution_reason = ?, updated_at = ? WHERE id = ?", (actor["id"], now, category, reason.strip(), now, alert_id))
    _action(tx, alert_id, actor, "resolve", f"[{category}] {reason.strip()}")
    audit.record(tx, "alert.resolved", "alert", alert_id,
                 {"from": alert["status"], "to": "RESOLVED", "category": category, "reason": reason.strip()}, actor)
    return get(tx, alert_id)
