"""Candidate alert endpoints."""
from __future__ import annotations

import json
from typing import Literal

from pydantic import BaseModel, Field
from starlette.requests import Request

from ..services import alerts as alert_service
from ..services import assessments as assessment_service
from .common import ApiError, body_as, db, ok, page, paging, require

STATUS_FILTERS = {
    "open": "status <> 'RESOLVED'", "resolved": "status = 'RESOLVED'", "all": "1 = 1",
    "REVIEW_REQUIRED": "status = 'REVIEW_REQUIRED'", "ACKNOWLEDGED": "status = 'ACKNOWLEDGED'",
    "ACTION_ASSIGNED": "status = 'ACTION_ASSIGNED'", "RESOLVED": "status = 'RESOLVED'",
}


@require("read")
async def list_alerts(request: Request, user: dict):
    limit, offset = paging(request)
    status = request.query_params.get("status", "open")
    if status not in STATUS_FILTERS:
        raise ApiError(422, "validation_error", f"status must be one of {sorted(STATUS_FILTERS)}.")
    where, params = [STATUS_FILTERS[status]], []
    for key in ("site_id", "hazard", "kind"):
        v = request.query_params.get(key)
        if v:
            where.append(f"a.{key} = ?")
            params.append(v)
    clause = " AND ".join(where)
    with db(request).tx() as tx:
        total = tx.scalar(f"SELECT COUNT(*) FROM alerts a WHERE {clause}", params)
        rows = tx.all(f"SELECT a.*, s.name AS site_name FROM alerts a JOIN sites s ON s.id = a.site_id WHERE {clause} "
                      f"ORDER BY CASE a.status WHEN 'REVIEW_REQUIRED' THEN 0 WHEN 'ACKNOWLEDGED' THEN 1 "
                      f"WHEN 'ACTION_ASSIGNED' THEN 2 ELSE 3 END, a.created_at DESC LIMIT ? OFFSET ?",
                      params + [limit, offset])
    return ok(page(rows, total, limit, offset))


@require("read")
async def get_alert(request: Request, user: dict):
    alert_id = request.path_params["alert_id"]
    with db(request).tx() as tx:
        try:
            alert = alert_service.get(tx, alert_id)
        except LookupError:
            raise ApiError(404, "not_found", "Alert not found.")
        site = tx.one("SELECT id, name, district, latitude, longitude, location_note FROM sites WHERE id = ?", (alert["site_id"],))
        trig = tx.one("SELECT * FROM assessments WHERE id = ?", (alert["latest_assessment_id"],))
        first = tx.one("SELECT * FROM assessments WHERE id = ?", (alert["first_assessment_id"],))
        triggering = assessment_service.hydrate(trig)
        current = assessment_service.latest_assessment(tx, alert["site_id"], alert["hazard"])
        ids = triggering.get("evidence_observation_ids", [])
        evidence = []
        if ids:
            marks = ",".join("?" for _ in ids)
            evidence = tx.all(f"SELECT id, sensor_id, metric, value, unit, observed_at, received_at, quality_status, origin, "
                              f"source_id FROM observations WHERE id IN ({marks}) ORDER BY observed_at DESC", ids)
        linked = tx.all("SELECT a.id, a.risk_tier, a.reliability, a.score, a.assessed_at FROM alert_assessments l "
                        "JOIN assessments a ON a.id = l.assessment_id WHERE l.alert_id = ? ORDER BY a.assessed_at DESC LIMIT 50",
                        (alert_id,))
        actions = tx.all("SELECT ac.*, u.display_name AS actor_name, u.role AS actor_role FROM alert_actions ac "
                         "JOIN users u ON u.id = ac.actor_id WHERE ac.alert_id = ? ORDER BY ac.created_at, ac.id", (alert_id,))
        history = tx.all("SELECT seq, occurred_at, actor_name, actor_role, event_type, details, hash FROM audit_log "
                         "WHERE entity_type = 'alert' AND entity_id = ? ORDER BY seq", (alert_id,))
        users = {u["id"]: u["display_name"] for u in tx.all("SELECT id, display_name FROM users")}
    for h in history:
        h["details"] = json.loads(h["details"])
    alert["acknowledged_by_name"] = users.get(alert["acknowledged_by"])
    alert["resolved_by_name"] = users.get(alert["resolved_by"])
    return ok({
        "alert": alert, "site": site,
        "first_assessment": assessment_service.hydrate(first),
        "triggering_assessment": triggering, "current_assessment": current,
        "evidence_observations": evidence, "linked_assessments": linked, "actions": actions, "history": history,
        "notice": "DEMO candidate alert for authorised review only. Not an official warning. No message has been sent.",
    })


class AckIn(BaseModel):
    notes: str = Field("", max_length=2000)


class ActionIn(BaseModel):
    action_type: Literal["field_verification", "escalation", "test_notification", "note"]
    notes: str = Field(min_length=3, max_length=2000)
    assignee: str | None = Field(None, max_length=120)


class ResolveIn(BaseModel):
    category: Literal["condition_cleared", "false_alarm", "confirmed_event", "data_issue", "exercise"]
    reason: str = Field(min_length=5, max_length=2000)


def _transition(request: Request, fn, *args):
    alert_id = request.path_params["alert_id"]
    with db(request).tx() as tx:
        try:
            return fn(tx, alert_id, *args)
        except LookupError:
            raise ApiError(404, "not_found", "Alert not found.")
        except alert_service.TransitionError as exc:
            raise ApiError(409, "invalid_transition", str(exc))


@require("alert_review")
async def acknowledge(request: Request, user: dict):
    body = await body_as(request, AckIn)
    return ok({"alert": _transition(request, alert_service.acknowledge, user, body.notes)})


@require("alert_review")
async def add_action(request: Request, user: dict):
    body = await body_as(request, ActionIn)
    return ok({"alert": _transition(request, alert_service.add_action, user, body.action_type, body.notes, body.assignee)})


@require("alert_review")
async def resolve(request: Request, user: dict):
    body = await body_as(request, ResolveIn)
    return ok({"alert": _transition(request, alert_service.resolve, user, body.category, body.reason)})
