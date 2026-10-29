"""Scenario simulator (DEMO ONLY).

Generates synthetic sensor time series for a site from a small set of scenario
parameters. Every observation written here has origin = 'SIMULATED' and is
attributed to the SIM-GATEWAY data source. Applying a scenario replaces the
site's previous SIMULATED observations; OBSERVED or IMPORTED observations are
never deleted.

The simulated gateway then keeps "reporting" at each sensor's interval, holding
the scenario's current conditions, so freshness behaves like a live feed.
"""
from __future__ import annotations

import json
import random
import uuid
from datetime import datetime, timedelta
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .. import clock
from ..db import Tx
from . import audit
from .risk_engine import merge_config

SIM_SOURCE_ID = "SIM-GATEWAY"
HISTORY_HOURS = 48
SENSOR_TYPES = ("rain_gauge", "soil_moisture", "extensometer", "river_stage")


class ScenarioParams(BaseModel):
    """Inputs for one site. Values are synthetic demonstration inputs."""
    # A misspelt parameter must fail loudly rather than be ignored (HDEWS-005).
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    rain_mm_h: float = Field(0.0, ge=0, le=150, description="Current rainfall intensity (mm/h)")
    rain_hours: float = Field(0.0, ge=0, le=24, description="How long the current rainfall has lasted (h)")
    background_rain_mm_h: float = Field(0.2, ge=0, le=50, description="Rainfall rate earlier in the last 24 h (mm/h)")
    soil_moisture_pct: float = Field(25.0, ge=0, le=60, description="Current volumetric soil moisture (%)")
    displacement_24h_mm: float = Field(0.2, ge=0, le=100, description="Slope displacement over the last 24 h (mm)")
    river_level_m: float | None = Field(None, ge=0, le=15, description="Current river stage (m); default = site normal")
    river_rise_1h_m: float = Field(0.0, ge=-2, le=5, description="River-stage change over the last hour (m)")
    offline_sensors: list[str] = Field(default_factory=list, description="Sensor types that stopped reporting")
    outage_minutes: int = Field(0, ge=0, le=2880)
    delayed_sensors: list[str] = Field(default_factory=list, description="Sensor types whose data arrives late")
    delay_minutes: int = Field(0, ge=0, le=720)

    @field_validator("offline_sensors", "delayed_sensors")
    @classmethod
    def _known_types(cls, v: list[str]) -> list[str]:
        bad = [t for t in v if t not in SENSOR_TYPES]
        if bad:
            raise ValueError(f"unknown sensor type(s) {bad}; allowed: {list(SENSOR_TYPES)}")
        return sorted(set(v))


PRESETS: dict[str, dict[str, Any]] = {
    "normal": {
        "label": "Normal conditions",
        "description": "Dry to light background rainfall, soil near baseline, negligible movement, river at normal stage.",
        "params": {},
    },
    "increasing_rainfall": {
        "label": "Increasing rainfall",
        "description": "Moderate rain (17 mm/h) for 3 h after a wet day; soil moisture rising.",
        "params": {"rain_mm_h": 17, "rain_hours": 3, "background_rain_mm_h": 1.5, "soil_moisture_pct": 37,
                   "displacement_24h_mm": 0.6, "river_rise_1h_m": 0.2, "river_offset_m": 0.7},
    },
    "rising_landslide_indicators": {
        "label": "Rising landslide indicators",
        "description": "Prolonged heavy rain, saturated soil and accelerating slope displacement.",
        "params": {"rain_mm_h": 22, "rain_hours": 4, "background_rain_mm_h": 3, "soil_moisture_pct": 45,
                   "displacement_24h_mm": 6.5, "river_rise_1h_m": 0.2, "river_offset_m": 0.9},
    },
    "rapid_river_rise": {
        "label": "Rapidly rising river level",
        "description": "Intense rainfall burst (35 mm/h) with the river above the site danger stage and rising fast.",
        "params": {"rain_mm_h": 35, "rain_hours": 2, "background_rain_mm_h": 1, "soil_moisture_pct": 34,
                   "displacement_24h_mm": 0.8, "river_rise_1h_m": 0.8, "river_offset_m": 2.9},
    },
    "sensor_outage_adverse_weather": {
        "label": "Sensor outage during adverse weather",
        "description": "Heavy rain while the soil-moisture and river-stage sensors have been offline for 7 h "
                       "and the extensometer link is delayed by 40 min.",
        "params": {"rain_mm_h": 18, "rain_hours": 3, "background_rain_mm_h": 2, "soil_moisture_pct": 41,
                   "displacement_24h_mm": 1.2, "river_rise_1h_m": 0.3, "river_offset_m": 1.2,
                   "offline_sensors": ["soil_moisture", "river_stage"], "outage_minutes": 420,
                   "delayed_sensors": ["extensometer"], "delay_minutes": 40},
    },
}


def normal_river_level(cfg: dict) -> float:
    return round(float(cfg["flash_flood"]["river_warning_level_m"]) - 1.4, 2)


def resolve_params(preset: str | None, overrides: dict | None, cfg: dict) -> ScenarioParams:
    base: dict[str, Any] = {}
    if preset:
        if preset not in PRESETS:
            raise ValueError(f"unknown preset '{preset}'")
        base = dict(PRESETS[preset]["params"])
    offset = base.pop("river_offset_m", 0.0)
    base.setdefault("river_level_m", round(normal_river_level(cfg) + offset, 2))
    base.update({k: v for k, v in (overrides or {}).items() if v is not None})
    return ScenarioParams(**base)


def _rng(site_id: str, sensor_type: str, t: datetime) -> random.Random:
    return random.Random(f"{site_id}|{sensor_type}|{int(t.timestamp())}")


def _value(sensor_type: str, p: ScenarioParams, hb: float, normal_level: float, soil_base: float,
           rng: random.Random, interval_h: float) -> float:
    """Value at `hb` hours before the scenario reference time."""
    if sensor_type == "rain_gauge":
        if hb < p.rain_hours:
            rate = p.rain_mm_h
        elif hb < 24:
            rate = p.background_rain_mm_h
        else:
            rate = p.background_rain_mm_h * 0.3
        if rate <= 0:
            return 0.0
        return round(max(0.0, rate * interval_h * (1 + rng.uniform(-0.08, 0.08))), 2)
    if sensor_type == "soil_moisture":
        ramp = max(p.rain_hours * 2, 6.0)
        frac = max(0.0, 1 - hb / ramp)
        return round(soil_base + (p.soil_moisture_pct - soil_base) * frac + rng.uniform(-0.3, 0.3), 2)
    if sensor_type == "extensometer":
        d0 = 12.0
        if hb <= 24:
            # Mild acceleration toward the present.
            frac = (24 - hb) / 24
            return round(d0 + p.displacement_24h_mm * frac ** 1.3 + rng.uniform(-0.02, 0.02), 3)
        return round(d0 - 0.05 * (hb - 24) / 24 + rng.uniform(-0.02, 0.02), 3)
    if sensor_type == "river_stage":
        target = p.river_level_m if p.river_level_m is not None else normal_level
        ramp = max(p.rain_hours + 1, 3.0)
        if hb < 1:
            level = target - p.river_rise_1h_m * hb
        elif hb < ramp:
            start = target - p.river_rise_1h_m
            level = start + (normal_level - start) * (hb - 1) / (ramp - 1)
        else:
            level = normal_level
        return round(max(0.0, level + rng.uniform(-0.01, 0.01)), 3)
    raise ValueError(sensor_type)


def _rows_for_sensor(site_id: str, sensor: dict, p: ScenarioParams, ref: datetime, start: datetime,
                     scenario_id: str, cfg: dict, hold_from: datetime | None = None) -> list[dict]:
    """Synthetic readings for (start, ref]. If `hold_from` is set, readings after it hold current conditions."""
    interval = int(sensor["expected_interval_s"])
    interval_h = interval / 3600
    normal_level = normal_river_level(cfg)
    soil_base = float(cfg["landslide"]["soil_moisture_baseline_pct"]) - 3
    offline = sensor["sensor_type"] in p.offline_sensors
    delay = timedelta(minutes=p.delay_minutes) if sensor["sensor_type"] in p.delayed_sensors else timedelta(0)
    outage_start = (hold_from or ref) - timedelta(minutes=p.outage_minutes) if offline else None
    rows = []
    # Align to the sensor interval grid.
    t = datetime.fromtimestamp((int(start.timestamp()) // interval + 1) * interval, tz=ref.tzinfo)
    while t <= ref:
        if outage_start is not None and t > outage_start:
            break
        if hold_from is not None and t > hold_from:
            # Continuation: hold current conditions (hb = 0); displacement keeps creeping at the same rate.
            hb = 0.0
            value = _value(sensor["sensor_type"], p, hb, normal_level, soil_base, _rng(site_id, sensor["sensor_type"], t), interval_h)
            if sensor["sensor_type"] == "extensometer":
                value = round(value + p.displacement_24h_mm * (t - hold_from).total_seconds() / 86400, 3)
            if sensor["sensor_type"] == "river_stage":
                value = round((p.river_level_m if p.river_level_m is not None else normal_level), 3)
        else:
            hb = ((hold_from or ref) - t).total_seconds() / 3600
            value = _value(sensor["sensor_type"], p, hb, normal_level, soil_base, _rng(site_id, sensor["sensor_type"], t), interval_h)
        received = t + delay
        if received <= ref:
            rows.append({
                "sensor_id": sensor["id"], "site_id": site_id, "source_id": SIM_SOURCE_ID, "metric": sensor["metric"],
                "value": value, "unit": sensor["unit"], "observed_at": clock.iso(t), "received_at": clock.iso(received),
                "quality_status": "good", "origin": "SIMULATED", "scenario_id": scenario_id,
                "provenance": f"Synthetic reading generated by HDEWS simulator (scenario {scenario_id}). Not a real measurement.",
            })
        t += timedelta(seconds=interval)
    return rows


def apply_scenario(tx: Tx, site_ids: list[str], preset: str | None, overrides: dict | None, actor: dict,
                   name: str | None = None) -> dict:
    ref = clock.now()
    scenario_id = "sc_" + uuid.uuid4().hex[:10]
    applied: dict[str, dict] = {}
    for site_id in site_ids:
        site = tx.one("SELECT id, config FROM sites WHERE id = ?", (site_id,))
        if not site:
            raise LookupError(site_id)
        cfg = merge_config(json.loads(site["config"]))
        params = resolve_params(preset, overrides, cfg)
        sensors = tx.all("SELECT * FROM sensors WHERE site_id = ? AND source_id = ? AND status <> 'decommissioned'",
                         (site_id, SIM_SOURCE_ID))
        tx.execute("DELETE FROM observations WHERE site_id = ? AND origin = 'SIMULATED'", (site_id,))
        rows: list[dict] = []
        for sensor in sensors:
            rows.extend(_rows_for_sensor(site_id, sensor, params, ref, ref - timedelta(hours=HISTORY_HOURS), scenario_id, cfg))
        _bulk_insert(tx, rows)
        state = {"scenario_id": scenario_id, "preset": preset, "params": params.model_dump(), "applied_at": clock.iso(ref)}
        tx.execute("UPDATE sites SET sim_state = ?, updated_at = ? WHERE id = ?", (json.dumps(state), clock.iso(ref), site_id))
        applied[site_id] = {"params": params.model_dump(), "observations_written": len(rows)}
    label = name or (PRESETS[preset]["label"] if preset else "Custom scenario")
    tx.insert("scenario_runs", {"id": scenario_id, "name": label, "site_ids": site_ids,
                                "params": {"preset": preset, "overrides": overrides or {}}, "applied_by": actor["id"],
                                "applied_at": clock.iso(ref)})
    audit.record(tx, "simulation.scenario_applied", "scenario", scenario_id,
                 {"name": label, "preset": preset, "site_ids": site_ids, "overrides": overrides or {},
                  "note": "All generated observations are SIMULATED."}, actor)
    return {"scenario_id": scenario_id, "name": label, "sites": applied}


def tick(tx: Tx) -> int:
    """Continue simulated telemetry up to now for every site with an active scenario."""
    ref = clock.now()
    written = 0
    for site in tx.all("SELECT id, config, sim_state FROM sites WHERE sim_state IS NOT NULL"):
        state = json.loads(site["sim_state"])
        cfg = merge_config(json.loads(site["config"]))
        params = ScenarioParams(**state["params"])
        hold_from = clock.parse(state["applied_at"])
        for sensor in tx.all("SELECT * FROM sensors WHERE site_id = ? AND source_id = ? AND status = 'active'",
                             (site["id"], SIM_SOURCE_ID)):
            last = tx.scalar("SELECT MAX(observed_at) FROM observations WHERE sensor_id = ? AND origin = 'SIMULATED'",
                             (sensor["id"],))
            start = clock.parse(last) if last else hold_from
            rows = _rows_for_sensor(site["id"], sensor, params, ref, start, state["scenario_id"], cfg, hold_from=hold_from)
            if sensor["sensor_type"] in params.delayed_sensors:
                # Delayed readings that have now "arrived" but were not written earlier.
                rows = [r for r in rows if r["observed_at"] > (last or "")]
            # These readings reach HDEWS now. After downtime they may have been observed hours ago (a
            # buffering gateway); received_at must record the true receipt time, never a past one (HDEWS-035).
            for r in rows:
                if r["received_at"] < clock.iso(ref):
                    r["received_at"] = clock.iso(ref)
            _bulk_insert(tx, rows)
            written += len(rows)
    return written


def _bulk_insert(tx: Tx, rows: list[dict]) -> None:
    if not rows:
        return
    cols = list(rows[0].keys())
    sql = (f"INSERT INTO observations ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)}) "
           "ON CONFLICT (sensor_id, observed_at, origin) DO NOTHING")
    for r in rows:
        tx.execute(sql, [r[c] for c in cols])
