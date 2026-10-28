"""Assessment orchestration: load observations, compute features, run the
baseline engine, persist the structured result and hand it to the alert service."""
from __future__ import annotations

import json
import uuid
from datetime import timedelta

from .. import clock
from ..db import Tx, loads
from . import alerts as alert_service
from . import audit
from .risk_engine import assess, build_features, merge_config

LOOKBACK_HOURS = 26


def load_site(tx: Tx, site_id: str) -> dict | None:
    site = tx.one("SELECT * FROM sites WHERE id = ?", (site_id,))
    if site:
        site["hazards"] = loads(site["hazards"], [])
        site["config"] = loads(site["config"], {})
        site["sim_state"] = loads(site["sim_state"])
    return site


def site_features(tx: Tx, site: dict, ref=None) -> tuple[dict, dict, list[dict]]:
    ref = ref or clock.now()
    cfg = merge_config(site["config"])
    sensors = tx.all("SELECT * FROM sensors WHERE site_id = ? ORDER BY id", (site["id"],))
    since = clock.iso(ref - timedelta(hours=LOOKBACK_HOURS))
    rows = tx.all(
        "SELECT id, sensor_id, value, observed_at, received_at, quality_status, origin FROM observations "
        "WHERE site_id = ? AND observed_at > ? AND observed_at <= ? AND received_at <= ? ORDER BY observed_at",
        (site["id"], since, clock.iso(ref), clock.iso(ref)))
    by_sensor: dict[str, list[dict]] = {}
    for r in rows:
        by_sensor.setdefault(r["sensor_id"], []).append(r)
    # Health must consider readings older than the lookback (e.g. an offline sensor's last reading).
    for s in sensors:
        if s["id"] not in by_sensor:
            last = tx.one(
                "SELECT id, sensor_id, value, observed_at, received_at, quality_status, origin FROM observations "
                "WHERE sensor_id = ? AND observed_at <= ? AND received_at <= ? ORDER BY observed_at DESC LIMIT 1",
                (s["id"], clock.iso(ref), clock.iso(ref)))
            if last:
                by_sensor[s["id"]] = [last]
    feats = build_features(sensors, by_sensor, cfg, ref)
    return feats, cfg, sensors


def latest_assessment(tx: Tx, site_id: str, hazard: str) -> dict | None:
    row = tx.one("SELECT * FROM assessments WHERE site_id = ? AND hazard = ? ORDER BY assessed_at DESC, rowid DESC LIMIT 1"
                 if tx.dialect == "sqlite" else
                 "SELECT * FROM assessments WHERE site_id = ? AND hazard = ? ORDER BY assessed_at DESC LIMIT 1",
                 (site_id, hazard))
    return hydrate(row) if row else None


def hydrate(row: dict) -> dict:
    payload = loads(row["payload"], {})
    payload["id"] = row["id"]
    payload["trigger"] = row["trigger"]
    payload["previous_assessment_id"] = row["previous_assessment_id"]
    return payload


def run_site(tx: Tx, site_id: str, trigger: str, actor: dict | None = None) -> list[dict]:
    site = load_site(tx, site_id)
    if not site:
        raise LookupError(site_id)
    feats, cfg, _ = site_features(tx, site)
    results = []
    for hazard in site["hazards"]:
        previous = latest_assessment(tx, site_id, hazard)
        result = assess(site, hazard, feats["indicators"], feats["health"], cfg, previous=previous)
        result["sensor_health"] = [h.as_dict() for h in feats["health"].values()]
        result["observed_rain_1h_mm"] = (feats["indicators"].get("rain_1h_mm").value
                                         if feats["indicators"].get("rain_1h_mm") else None)
        assessment_id = "as_" + uuid.uuid4().hex[:12]
        result["id"] = assessment_id
        tx.insert("assessments", {
            "id": assessment_id, "site_id": site_id, "hazard": hazard, "risk_tier": result["risk_tier"],
            "reliability": result["reliability"], "score": result["score"], "rule_version": result["rule_version"],
            "assessed_at": result["assessed_at"], "trigger": trigger, "data_origin": result["data_origin"],
            "payload": json.dumps(result, separators=(",", ":"), default=str),
            "previous_assessment_id": previous["id"] if previous else None,
        })
        changed = (not previous or previous["risk_tier"] != result["risk_tier"]
                   or previous["reliability"] != result["reliability"])
        if changed:
            audit.record(tx, "assessment.changed", "site", site_id, {
                "assessment_id": assessment_id, "hazard": hazard, "risk_tier": result["risk_tier"],
                "reliability": result["reliability"], "previous_tier": previous["risk_tier"] if previous else None,
                "trigger": trigger, "data_origin": result["data_origin"], "rule_version": result["rule_version"],
            }, actor)
        result["previous_assessment_id"] = previous["id"] if previous else None
        result["trigger"] = trigger
        alert_service.process_assessment(tx, site, result, cfg, actor)
        results.append(result)
    return results


def run_all(tx: Tx, trigger: str, actor: dict | None = None) -> list[dict]:
    out = []
    for row in tx.all("SELECT id FROM sites ORDER BY id"):
        out.extend(run_site(tx, row["id"], trigger, actor))
    return out
