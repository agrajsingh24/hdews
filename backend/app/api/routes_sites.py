"""Sites, observations, assessments and explanations."""
from __future__ import annotations

import json
from datetime import timedelta

from pydantic import BaseModel
from starlette.requests import Request

from .. import clock
from ..services import assessments as assessment_service
from ..services import audit, explanations
from ..services.risk_engine import merge_config, validate_site_overrides
from .common import ApiError, body_as, db, ok, page, paging, require, settings


def _site_or_404(tx, site_id: str) -> dict:
    site = assessment_service.load_site(tx, site_id)
    if not site:
        raise ApiError(404, "not_found", f"Site '{site_id}' not found.")
    return site


@require("read")
async def list_sites(request: Request, user: dict):
    with db(request).tx() as tx:
        out = []
        for row in tx.all("SELECT id FROM sites ORDER BY id"):
            site = assessment_service.load_site(tx, row["id"])
            feats, _, sensors = assessment_service.site_features(tx, site)
            latest = {h: assessment_service.latest_assessment(tx, site["id"], h) for h in site["hazards"]}
            out.append({
                "id": site["id"], "name": site["name"], "district": site["district"], "latitude": site["latitude"],
                "longitude": site["longitude"], "elevation_m": site["elevation_m"], "hazards": site["hazards"],
                "sensor_count": len(sensors),
                "sensor_states": [h.state for h in feats["health"].values()],
                "assessments": {h: a and {k: a[k] for k in ("id", "risk_tier", "reliability", "assessed_at", "data_origin",
                                                             "summary", "tier_is_lower_bound")} for h, a in latest.items()},
                "scenario": site["sim_state"] and {"preset": site["sim_state"]["preset"],
                                                   "applied_at": site["sim_state"]["applied_at"]},
            })
    return ok({"items": out, "total": len(out)})


@require("read")
async def get_site(request: Request, user: dict):
    site_id = request.path_params["site_id"]
    with db(request).tx() as tx:
        site = _site_or_404(tx, site_id)
        feats, cfg, sensors = assessment_service.site_features(tx, site)
        health = feats["health"]
        sensor_out = []
        for s in sensors:
            h = health.get(s["id"])
            sensor_out.append({**s, "health": h.as_dict() if h else None,
                               "source": tx.one("SELECT id, name, origin FROM data_sources WHERE id = ?", (s["source_id"],))})
        latest = {h: assessment_service.latest_assessment(tx, site_id, h) for h in site["hazards"]}
        alerts = tx.all("SELECT id, hazard, kind, severity, status, title, created_at, resolved_at, data_origin FROM alerts "
                        "WHERE site_id = ? ORDER BY created_at DESC LIMIT 20", (site_id,))
        incidents = tx.all("SELECT id, title, hazard, event_date, origin, verification_status, source_url FROM incidents "
                           "WHERE related_site_id = ? ORDER BY event_date DESC", (site_id,))
    indicators = {k: {"key": i.key, "label": i.label, "unit": i.unit, "value": i.value, "status": i.status,
                      "as_of": i.as_of, "coverage": i.coverage, "notes": i.notes, "origins": sorted(i.origins)}
                  for k, i in feats["indicators"].items()}
    return ok({"site": {k: v for k, v in site.items()}, "effective_config": cfg, "sensors": sensor_out,
               "indicators": indicators, "assessments": latest, "alerts": alerts, "incidents": incidents})


@require("read")
async def site_observations(request: Request, user: dict):
    site_id = request.path_params["site_id"]
    try:
        hours = int(request.query_params.get("hours", 24))
    except ValueError:
        raise ApiError(422, "validation_error", "hours must be an integer.")
    if not 1 <= hours <= 168:
        raise ApiError(422, "validation_error", "hours must be between 1 and 168.")
    ref = clock.now()
    with db(request).tx() as tx:
        _site_or_404(tx, site_id)
        sensors = tx.all("SELECT id, sensor_type, label, unit, metric, expected_interval_s FROM sensors WHERE site_id = ?",
                         (site_id,))
        rows = tx.all("SELECT id, sensor_id, value, observed_at, received_at, quality_status, origin, source_id FROM observations "
                      "WHERE site_id = ? AND observed_at > ? AND received_at <= ? ORDER BY observed_at",
                      (site_id, clock.iso(ref - timedelta(hours=hours)), clock.iso(ref)))
    series = {s["id"]: {**s, "points": []} for s in sensors}
    for r in rows:
        series[r["sensor_id"]]["points"].append(
            {"id": r["id"], "t": r["observed_at"], "r": r["received_at"], "v": r["value"], "q": r["quality_status"],
             "o": r["origin"], "src": r["source_id"]})
    return ok({"site_id": site_id, "hours": hours, "generated_at": clock.iso(ref), "series": list(series.values())})


@require("run_assessment")
async def run_site_assessment(request: Request, user: dict):
    site_id = request.path_params["site_id"]
    with db(request).tx() as tx:
        _site_or_404(tx, site_id)
        results = assessment_service.run_site(tx, site_id, trigger=f"manual:{user['username']}", actor=user)
    return ok({"assessments": results})


class ConfigIn(BaseModel):
    overrides: dict


@require("manage_config")
async def update_site_config(request: Request, user: dict):
    site_id = request.path_params["site_id"]
    body = await body_as(request, ConfigIn)
    errors = validate_site_overrides(body.overrides)
    if errors:
        raise ApiError(422, "validation_error", "Threshold configuration is invalid.", errors)
    with db(request).tx() as tx:
        site = _site_or_404(tx, site_id)
        tx.execute("UPDATE sites SET config = ?, updated_at = ? WHERE id = ?",
                   (json.dumps(body.overrides), clock.now_iso(), site_id))
        audit.record(tx, "site.config_changed", "site", site_id,
                     {"before": site["config"], "after": body.overrides,
                      "note": "Demo thresholds edited; still uncalibrated."}, user)
        results = assessment_service.run_site(tx, site_id, trigger=f"config_change:{user['username']}", actor=user)
    return ok({"effective_config": merge_config(body.overrides), "assessments": results})


@require("read")
async def list_assessments(request: Request, user: dict):
    limit, offset = paging(request)
    where, params = [], []
    for key in ("site_id", "hazard", "risk_tier", "reliability"):
        v = request.query_params.get(key)
        if v:
            where.append(f"{key} = ?")
            params.append(v)
    clause = ("WHERE " + " AND ".join(where)) if where else ""
    with db(request).tx() as tx:
        total = tx.scalar(f"SELECT COUNT(*) FROM assessments {clause}", params)
        rows = tx.all(f"SELECT id, site_id, hazard, risk_tier, reliability, score, rule_version, assessed_at, trigger, "
                      f"data_origin FROM assessments {clause} ORDER BY assessed_at DESC LIMIT ? OFFSET ?",
                      params + [limit, offset])
    return ok(page(rows, total, limit, offset))


@require("read")
async def get_assessment(request: Request, user: dict):
    with db(request).tx() as tx:
        row = tx.one("SELECT * FROM assessments WHERE id = ?", (request.path_params["assessment_id"],))
        if not row:
            raise ApiError(404, "not_found", "Assessment not found.")
        a = assessment_service.hydrate(row)
        ids = a.get("evidence_observation_ids", [])
        evidence = []
        if ids:
            marks = ",".join("?" for _ in ids)
            evidence = tx.all(f"SELECT id, sensor_id, metric, value, unit, observed_at, received_at, quality_status, origin, "
                              f"source_id, provenance FROM observations WHERE id IN ({marks}) ORDER BY observed_at", ids)
    a["evidence_observations"] = evidence
    a["evidence_note"] = (None if len(evidence) == len(ids) else
                          "Some referenced observations are no longer stored (simulated data replaced by a newer scenario).")
    return ok(a)


@require("read")
async def explain_assessment(request: Request, user: dict):
    with db(request).tx() as tx:
        row = tx.one("SELECT * FROM assessments WHERE id = ?", (request.path_params["assessment_id"],))
    if not row:
        raise ApiError(404, "not_found", "Assessment not found.")
    return ok(explanations.explain(assessment_service.hydrate(row), settings(request)))
