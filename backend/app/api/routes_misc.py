"""Incidents, data sources, audit log, evaluation, demo simulator and ingestion."""
from __future__ import annotations

import json
import math

from pydantic import BaseModel, Field, ValidationError
from starlette.requests import Request

from .. import clock
from ..services import assessments as assessment_service
from ..services import audit, data_sources, ingestion, simulator
from ..services.risk_engine import merge_config
from .common import ApiError, validation_details, body_as, client_key, db, ok, page, paging, require, settings

@require("read")
async def list_incidents(request: Request, user: dict):
    limit, offset = paging(request)
    where, params = [], []
    q = request.query_params
    for key in ("hazard", "origin", "verification_status", "related_site_id"):
        if q.get(key):
            where.append(f"{key} = ?")
            params.append(q[key])
    if q.get("from"):
        where.append("event_date >= ?")
        params.append(q["from"])
    if q.get("to"):
        where.append("event_date <= ?")
        params.append(q["to"])
    if q.get("q"):
        where.append("(LOWER(title) LIKE ? ESCAPE '\\' OR LOWER(location_name) LIKE ? ESCAPE '\\' "
                     "OR LOWER(description) LIKE ? ESCAPE '\\')")
        term = "%" + like_escape(q["q"].lower()[:80]) + "%"
        params += [term, term, term]
    clause = ("WHERE " + " AND ".join(where)) if where else ""
    with db(request).tx() as tx:
        total = tx.scalar(f"SELECT COUNT(*) FROM incidents {clause}", params)
        rows = tx.all(f"SELECT * FROM incidents {clause} ORDER BY event_date DESC LIMIT ? OFFSET ?", params + [limit, offset])
    return ok(page(rows, total, limit, offset))


def like_escape(text: str) -> str:
    """Treat user search text literally: % and _ are not wildcards (HDEWS-020)."""
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _km(lat1, lon1, lat2, lon2) -> float:
    p = math.pi / 180
    a = 0.5 - math.cos((lat2 - lat1) * p) / 2 + math.cos(lat1 * p) * math.cos(lat2 * p) * (1 - math.cos((lon2 - lon1) * p)) / 2
    return 12742 * math.asin(math.sqrt(a))


@require("read")
async def get_incident(request: Request, user: dict):
    with db(request).tx() as tx:
        inc = tx.one("SELECT * FROM incidents WHERE id = ?", (request.path_params["incident_id"],))
        if not inc:
            raise ApiError(404, "not_found", "Incident not found.")
        sites = tx.all("SELECT id, name, latitude, longitude FROM sites")
        # Associated observations: only those recorded at the related site within ±1 day of the event date.
        obs = []
        if inc["related_site_id"]:
            obs = tx.all("SELECT id, sensor_id, metric, value, unit, observed_at, origin FROM observations "
                         "WHERE site_id = ? AND observed_at >= ? AND observed_at <= ? ORDER BY observed_at LIMIT 500",
                         (inc["related_site_id"], inc["event_date"] + "T00:00:00Z", inc["event_date"] + "T23:59:59Z"))
    nearby = sorted(({**s, "distance_km": round(_km(inc["latitude"], inc["longitude"], s["latitude"], s["longitude"]), 1)}
                     for s in sites), key=lambda s: s["distance_km"])[:3]
    return ok({"incident": inc, "nearby_sites": nearby, "associated_observations": obs,
               "associated_observations_note": None if obs else
               "No HDEWS observations exist for this date and location. The prototype holds only recent simulated "
               "telemetry; historical time series would require an archived, licensed dataset."})


@require("read")
async def list_data_sources(request: Request, user: dict):
    with db(request).tx() as tx:
        return ok({"items": data_sources.list_with_health(tx), "generated_at": clock.now_iso()})


@require("read")
async def audit_log(request: Request, user: dict):
    limit, offset = paging(request, default=50, maximum=200)
    where, params = [], []
    for key in ("entity_type", "entity_id", "event_type", "actor_id"):
        v = request.query_params.get(key)
        if v:
            where.append(f"{key} = ?")
            params.append(v)
    prefix = request.query_params.get("event_prefix")
    if prefix:
        where.append("event_type LIKE ? ESCAPE '\\'")
        params.append(like_escape(prefix[:80]) + "%")
    clause = ("WHERE " + " AND ".join(where)) if where else ""
    with db(request).tx() as tx:
        total = tx.scalar(f"SELECT COUNT(*) FROM audit_log {clause}", params)
        rows = tx.all(f"SELECT * FROM audit_log {clause} ORDER BY seq DESC LIMIT ? OFFSET ?", params + [limit, offset])
    for r in rows:
        r["details"] = json.loads(r["details"])
    return ok(page(rows, total, limit, offset))


@require("read")
async def audit_verify(request: Request, user: dict):
    with db(request).tx() as tx:
        return ok({**audit.verify_chain(tx), "checked_at": clock.now_iso()})


@require("read")
async def evaluation(request: Request, user: dict):
    with db(request).tx() as tx:
        runs = tx.all("SELECT * FROM evaluation_runs ORDER BY created_at DESC")
    for r in runs:
        r["metrics"] = json.loads(r["metrics"])
        r["regions"] = json.loads(r["regions"])
    return ok({
        "status": "EVALUATED" if runs else "NOT_EVALUATED",
        "message": None if runs else (
            "Not evaluated yet. No labelled, time-aligned event dataset is available for the pilot area, so no "
            "model performance can be reported. The baseline rules use uncalibrated demonstration thresholds."),
        "runs": runs,
        "requirements": [
            "A documented landslide / flash-flood event inventory with event times and locations, validated with domain experts.",
            "Time-aligned rainfall, soil-moisture, displacement and river-stage observations covering events and non-events.",
            "Labels defined before modelling; no measurements recorded after the event used as features (leakage).",
            "Temporal and geographic hold-out splits, not random row splits.",
        ],
        "metrics_reported_when_available": ["precision", "recall", "PR-AUC", "false-alarm rate", "missed-event rate",
                                            "warning lead time (where event onset times are reliable)",
                                            "calibration (only if probabilities are shown)"],
        "how_to_run": "python -m ml.evaluate --dataset <labelled.csv> --dataset-name <name> --dataset-version <v> "
                      "(see ml/README.md for the required schema).",
    })


# ---- demo simulator ---------------------------------------------------------

def _demo_guard(request: Request) -> None:
    if not settings(request).demo_endpoints_active:
        raise ApiError(404, "not_found", "Demo endpoints are disabled in this configuration.")


@require("read")
async def demo_presets(request: Request, user: dict):
    _demo_guard(request)
    with db(request).tx() as tx:
        sites = [assessment_service.load_site(tx, r["id"]) for r in tx.all("SELECT id FROM sites ORDER BY id")]
    return ok({
        "presets": [{"id": k, "label": v["label"], "description": v["description"], "params": v["params"]}
                    for k, v in simulator.PRESETS.items()],
        "parameters": {name: {"description": f.description, "default": f.get_default(call_default_factory=True)}
                       for name, f in simulator.ScenarioParams.model_fields.items()},
        "sensor_types": list(simulator.SENSOR_TYPES),
        "sites": [{"id": s["id"], "name": s["name"], "hazards": s["hazards"], "sim_state": s["sim_state"],
                   "normal_river_level_m": simulator.normal_river_level(merge_config(s["config"]))}
                  for s in sites],
        "note": "Every observation produced by the simulator is labelled SIMULATED. Scenarios never represent real events.",
    })


class ScenarioIn(BaseModel):
    site_ids: list[str] = Field(min_length=1, max_length=50)
    preset: str | None = None
    overrides: dict | None = None
    name: str | None = Field(None, max_length=80)


@require("run_scenario")
async def apply_scenario(request: Request, user: dict):
    _demo_guard(request)
    body = await body_as(request, ScenarioIn)
    if not body.preset and not body.overrides:
        raise ApiError(422, "validation_error", "Provide a preset, overrides, or both.")
    body.site_ids = list(dict.fromkeys(body.site_ids))  # duplicates would apply the scenario twice
    if body.preset and body.preset not in simulator.PRESETS:
        raise ApiError(422, "validation_error", f"Unknown preset '{body.preset}'.")
    try:
        with db(request).tx() as tx:
            result = simulator.apply_scenario(tx, body.site_ids, body.preset, body.overrides, user, body.name)
            assessed = []
            for site_id in body.site_ids:
                assessed.extend(assessment_service.run_site(tx, site_id, trigger=f"scenario:{result['scenario_id']}", actor=user))
    except LookupError as exc:
        raise ApiError(404, "not_found", f"Site '{exc.args[0]}' not found.")
    except ValidationError as exc:
        raise ApiError(422, "validation_error", "Scenario parameters are invalid.", validation_details(exc))
    return ok({**result, "assessments": [
        {k: a[k] for k in ("id", "site_id", "hazard", "risk_tier", "reliability", "score", "summary", "data_origin")}
        for a in assessed]})


# ---- ingestion --------------------------------------------------------------

async def ingest(request: Request):
    request.app.state.ingest_limiter.check(client_key(request))
    source_id = request.path_params["source_id"]
    batch = await body_as(request, ingestion.IngestBatch)
    with db(request).tx() as tx:
        try:
            source = ingestion.authenticate_source(tx, source_id, request.headers.get("x-hdews-ingest-key"))
        except LookupError:
            raise ApiError(404, "not_found", "Unknown push source.")
        except ingestion.IngestAuthError as exc:
            raise ApiError(401, "ingest_unauthorized", str(exc))
        result = ingestion.ingest(tx, source, batch)
        for site_id in result["sites"]:
            assessment_service.run_site(tx, site_id, trigger=f"ingestion:{source_id}")
    return ok(result, status=202 if result["accepted"] else 200)
