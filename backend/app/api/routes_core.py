"""Health, metadata, authentication, overview and map layers."""
from __future__ import annotations

import json
from datetime import timedelta

from pydantic import BaseModel, Field
from starlette.requests import Request

from .. import clock, security
from ..config import REPO_ROOT
from ..services import audit
from ..services.assessments import latest_assessment
from ..services.risk_engine import DEFAULT_CONFIG, RULE_VERSION, THRESHOLD_STATUS
from ..services.risk_engine.playbook import PLAYBOOK_VERSION
from .common import ApiError, body_as, client_key, current_user, db, ok, require, settings

SAFETY_NOTICE = ("HDEWS is a research prototype and decision-support demonstrator. It is not a certified or official "
                 "warning service. Candidate alerts are for authorised human review only; nothing is sent to the public. "
                 "Thresholds are uncalibrated demonstration settings. Follow the responsible authority's approved SOPs.")

async def health(request: Request):
    with db(request).tx() as tx:
        tx.scalar("SELECT 1")
        last_obs = tx.scalar("SELECT MAX(received_at) FROM observations")
    return ok({"status": "ok", "time": clock.now_iso(), "database": db(request).dialect,
               "last_observation_received_at": last_obs, "environment": settings(request).app_env})


async def meta(request: Request):
    s = settings(request)
    return ok({
        "app": "HDEWS — Himalayan Disaster Early Warning System (prototype)",
        "environment": s.app_env, "demo_endpoints": s.demo_endpoints_active,
        "demo_login_hint": (None if s.is_production else
                            "Demo accounts: admin, analyst, reviewer, viewer. Password is set by HDEWS_DEMO_PASSWORD "
                            "(default 'hdews-demo')."),
        "rule_version": RULE_VERSION, "threshold_status": THRESHOLD_STATUS, "playbook_version": PLAYBOOK_VERSION,
        "llm_provider": s.llm_provider if s.llm_api_key else "none",
        "safety_notice": SAFETY_NOTICE, "server_time": clock.now_iso(),
    })


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


async def login(request: Request):
    request.app.state.login_limiter.check(client_key(request))
    body = await body_as(request, LoginIn)
    with db(request).tx() as tx:
        user = tx.one("SELECT * FROM users WHERE username = ?", (body.username.strip().lower(),))
        if not user or user["status"] != "active" or not security.verify_password(body.password, user["password_hash"]):
            raise ApiError(401, "invalid_credentials", "Username or password is incorrect.")
        token, expires = security.create_session(tx, user["id"], settings(request).session_ttl_hours)
        audit.record(tx, "auth.login", "user", user["id"], {"username": user["username"]},
                     {"id": user["id"], "display_name": user["display_name"], "role": user["role"]})
    return ok({"token": token, "expires_at": expires,
               "user": {k: user[k] for k in ("id", "username", "display_name", "role")}})


async def logout(request: Request):
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        with db(request).tx() as tx:
            tx.execute("DELETE FROM sessions WHERE token_hash = ?", (security.hash_token(header[7:].strip()),))
    return ok({"ok": True})


async def me(request: Request):
    user = current_user(request)
    if not user:
        raise ApiError(401, "unauthenticated", "Sign in to continue.")
    perms = sorted(p for p in security.PERMISSIONS if security.can(user, p))
    return ok({"user": {k: user[k] for k in ("id", "username", "display_name", "role")}, "permissions": perms})


@require("read")
async def overview(request: Request, user: dict):
    ref = clock.now()
    since24 = clock.iso(ref - timedelta(hours=24))
    with db(request).tx() as tx:
        sites = tx.all("SELECT id, name, hazards, latitude, longitude, sim_state FROM sites ORDER BY id")
        site_rows = []
        tier_counts: dict[str, int] = {}
        reliability_counts: dict[str, int] = {}
        for s in sites:
            hazards = json.loads(s["hazards"])
            latest = {}
            for h in hazards:
                a = latest_assessment(tx, s["id"], h)
                if a:
                    latest[h] = {"id": a["id"], "risk_tier": a["risk_tier"], "reliability": a["reliability"],
                                 "assessed_at": a["assessed_at"], "summary": a["summary"], "data_origin": a["data_origin"],
                                 "tier_is_lower_bound": a["tier_is_lower_bound"]}
                    tier_counts[a["risk_tier"]] = tier_counts.get(a["risk_tier"], 0) + 1
                    reliability_counts[a["reliability"]] = reliability_counts.get(a["reliability"], 0) + 1
            sim = json.loads(s["sim_state"]) if s["sim_state"] else None
            site_rows.append({"id": s["id"], "name": s["name"], "latitude": s["latitude"], "longitude": s["longitude"],
                              "hazards": hazards, "latest": latest,
                              "scenario": sim and {"preset": sim["preset"], "applied_at": sim["applied_at"]}})
        open_alerts = tx.all("SELECT id, site_id, hazard, kind, severity, status, title, created_at, data_origin FROM alerts "
                             "WHERE status <> 'RESOLVED' ORDER BY created_at DESC")
        sensors = tx.all("SELECT id, site_id, sensor_type, label, expected_interval_s, status FROM sensors")
        sensor_states: dict[str, int] = {}
        for sn in sensors:
            last = tx.scalar("SELECT MAX(observed_at) FROM observations WHERE sensor_id = ? AND received_at <= ?",
                             (sn["id"], clock.iso(ref)))
            if sn["status"] == "maintenance":
                st = "MAINTENANCE"
            elif not last:
                st = "NO_DATA"
            else:
                age = (ref - clock.parse(last)).total_seconds()
                st = "OFFLINE" if age > DEFAULT_CONFIG["freshness"]["offline_after_s"] else \
                    "STALE" if age > DEFAULT_CONFIG["freshness"]["stale_multiplier"] * sn["expected_interval_s"] else "FRESH"
            sensor_states[st] = sensor_states.get(st, 0) + 1
        origin_counts = {r["origin"]: r["n"] for r in tx.all(
            "SELECT origin, COUNT(*) AS n FROM observations WHERE observed_at > ? GROUP BY origin", (since24,))}
        rain_rows = tx.all(
            "SELECT o.site_id, o.observed_at, o.value FROM observations o JOIN sensors s ON s.id = o.sensor_id "
            "WHERE s.sensor_type = 'rain_gauge' AND o.observed_at > ? AND o.received_at <= ? "
            "AND o.quality_status IN ('good','suspect') ORDER BY o.observed_at", (since24, clock.iso(ref)))
        recent_obs = tx.all(
            "SELECT o.id, o.site_id, o.sensor_id, o.metric, o.value, o.unit, o.observed_at, o.received_at, o.origin, "
            "o.quality_status FROM observations o ORDER BY o.received_at DESC, o.id DESC LIMIT 8")
        tier_changes = tx.all(
            "SELECT occurred_at, entity_id, details FROM audit_log WHERE event_type = 'assessment.changed' "
            "ORDER BY seq DESC LIMIT 15")
        incidents = tx.all("SELECT id, title, hazard, event_date, origin, verification_status FROM incidents "
                           "ORDER BY event_date DESC LIMIT 4")
    # Hourly rainfall per site (sum of samples per clock hour) for the last 24 h.
    hours = [clock.iso((ref - timedelta(hours=i)).replace(minute=0, second=0)) for i in range(23, -1, -1)]
    rain: dict[str, dict[str, float]] = {s["id"]: {h: 0.0 for h in hours} for s in sites}
    for r in rain_rows:
        bucket = clock.iso(clock.parse(r["observed_at"]).replace(minute=0, second=0))
        if bucket in rain.get(r["site_id"], {}):
            rain[r["site_id"]][bucket] += r["value"]
    return ok({
        "generated_at": clock.iso(ref),
        "pilot_area": "Rudraprayag district, Uttarakhand (pilot study area)",
        "data_mode": _data_mode(origin_counts),
        "observation_origin_counts_24h": origin_counts,
        "sites": site_rows,
        "tier_counts": tier_counts, "reliability_counts": reliability_counts,
        "open_alerts": open_alerts,
        "open_alert_counts": {
            "REVIEW_REQUIRED": sum(a["status"] == "REVIEW_REQUIRED" for a in open_alerts),
            "ACKNOWLEDGED": sum(a["status"] == "ACKNOWLEDGED" for a in open_alerts),
            "ACTION_ASSIGNED": sum(a["status"] == "ACTION_ASSIGNED" for a in open_alerts),
        },
        "sensor_states": sensor_states, "sensor_total": len(sensors),
        "rain_hourly": {"hours": hours, "unit": "mm per hour",
                        "series": {k: [round(v[h], 1) for h in hours] for k, v in rain.items()}},
        "recent_observations": recent_obs,
        "tier_changes": [{"occurred_at": t["occurred_at"], "site_id": t["entity_id"], **json.loads(t["details"])}
                         for t in tier_changes],
        "recent_incidents": incidents,
    })


def _data_mode(origin_counts: dict) -> str:
    present = [o for o in ("OBSERVED", "IMPORTED", "SIMULATED") if origin_counts.get(o)]
    if not present:
        return "NO_DATA"
    return present[0] if len(present) == 1 else "MIXED"


@require("read")
async def map_layers(request: Request, user: dict):
    doc = json.loads((REPO_ROOT / "data" / "sample" / "sites.json").read_text())
    with db(request).tx() as tx:
        sites = tx.all("SELECT id, name, latitude, longitude, hazards, elevation_m, location_note FROM sites ORDER BY id")
        out_sites = []
        for s in sites:
            hazards = json.loads(s["hazards"])
            latest = {h: latest_assessment(tx, s["id"], h) for h in hazards}
            out_sites.append({**s, "hazards": hazards, "assessments": {
                h: a and {"id": a["id"], "risk_tier": a["risk_tier"], "reliability": a["reliability"],
                          "assessed_at": a["assessed_at"], "data_origin": a["data_origin"]} for h, a in latest.items()}})
        incidents = tx.all("SELECT id, title, hazard, event_date, latitude, longitude, origin, verification_status, "
                           "location_precision FROM incidents")
        open_alerts = tx.all("SELECT site_id, kind, status FROM alerts WHERE status <> 'RESOLVED'")
    zones = [
        {"id": f"zone-{s['id']}", "site_id": s["id"], "name": f"Demo hazard zone — {s['name']}",
         "center": [s["longitude"], s["latitude"]], "radius_km": 2.5 if "flash_flood" in s["hazards"] else 1.5,
         "simulated": True}
        for s in out_sites
    ]
    return ok({
        "pilot_area": {**doc["pilot_area"], "simulated_boundary": True},
        "layers": {
            "sites": {"label": "Monitoring sites", "items": out_sites,
                      "metadata": "Simulated monitoring points at approximate locality coordinates."},
            "hazard_zones": {"label": "Demo hazard zones", "items": zones,
                             "metadata": "SIMULATED illustrative buffers around sites — not mapped hazard zones."},
            "rivers": {"label": "Rivers (schematic)",
                       "items": [{"name": k, "coordinates": v} for k, v in doc["context_lines"].items() if not k.startswith("_")],
                       "metadata": doc["context_lines"]["_comment"]},
            "places": {"label": "Reference places", "items": doc["places"], "metadata": "Approximate locality points."},
            "incidents": {"label": "Historical incidents", "items": incidents,
                          "metadata": "IMPORTED = public report with source link; SYNTHETIC = demo only."},
        },
        "open_alerts": open_alerts,
        "basemap": {"optional_tiles": "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
                    "attribution": "© OpenStreetMap contributors",
                    "note": "Online tiles load only if the browser has internet access; the map works without them."},
        "generated_at": clock.now_iso(),
    })


@require("read")
async def rules(request: Request, user: dict):
    from ..services.risk_engine.rules import RULES
    from ..services.risk_engine.playbook import _STEPS, _DATA_STEPS
    return ok({
        "rule_version": RULE_VERSION, "threshold_status": THRESHOLD_STATUS, "defaults": DEFAULT_CONFIG,
        "indicators": {h: [{"key": r.key, "critical": r.critical, "watch_points": r.watch_points,
                            "high_points": r.high_points, "threshold": r.threshold_label(DEFAULT_CONFIG)}
                           for r in rs] for h, rs in RULES.items()},
        "tier_logic": [
            "Each indicator is compared with site-specific demo thresholds and awarded ordinal points (watch / high).",
            "Score ≥ high_min_score → HIGH; ≥ elevated_min_score → ELEVATED; otherwise LOW.",
            "Reliability is POOR if any critical input is missing or stale; DEGRADED if any input is incomplete, "
            "delayed, suspect or a non-critical input is missing; otherwise GOOD.",
            "If reliability is POOR and the available evidence scores LOW, the tier is INSUFFICIENT_DATA (never LOW).",
            "If inputs are missing but the available evidence already scores ELEVATED/HIGH, that tier is kept and "
            "marked as a lower bound; max_possible_tier shows how far missing inputs could move it.",
            "Points are not probabilities and have not been calibrated against events.",
        ],
        "playbook": {"version": PLAYBOOK_VERSION,
                     "steps": {f"{h}:{t}": s for (h, t), s in _STEPS.items()}, "data_gap_steps": _DATA_STEPS},
    })
