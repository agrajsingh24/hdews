"""Feature extraction: turn raw sensor observations into indicators with explicit
freshness, coverage, quality and provenance.

An indicator `status` is one of:
  available   - computed from fresh, sufficiently complete, good-quality data
  incomplete  - computed, but from fewer samples than expected (value is a lower bound for sums)
  stale       - sensor has not reported recently; value reflects the last data received
  missing     - no usable data (no sensor, offline beyond the limit, or no good samples)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from ... import clock

SENSOR_METRICS = {
    "rain_gauge": ("rain_mm", "mm"),
    "soil_moisture": ("soil_moisture_vwc_pct", "% VWC"),
    "extensometer": ("displacement_mm", "mm"),
    "river_stage": ("river_stage_m", "m"),
}


@dataclass
class SensorHealth:
    sensor_id: str
    sensor_type: str
    label: str
    state: str  # FRESH | STALE | OFFLINE | NO_DATA | MAINTENANCE
    last_observed_at: str | None
    last_received_at: str | None
    age_s: float | None
    delay_s: float | None
    delayed: bool
    expected_interval_s: int
    latest_value: float | None
    latest_quality: str | None
    latest_origin: str | None
    latest_observation_id: int | None

    def as_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


@dataclass
class Indicator:
    key: str
    label: str
    unit: str
    value: float | None
    status: str
    sensor_id: str | None
    as_of: str | None
    evidence_ids: list[int] = field(default_factory=list)
    coverage: float | None = None
    notes: list[str] = field(default_factory=list)
    origins: set[str] = field(default_factory=set)

    @property
    def usable(self) -> bool:
        return self.status in {"available", "incomplete", "stale"} and self.value is not None


def sensor_health(sensor: dict, observations: list[dict], cfg: dict, ref: datetime) -> SensorHealth:
    interval = int(sensor["expected_interval_s"])
    fresh_cfg = cfg["freshness"]
    good = [o for o in observations if o["quality_status"] in ("good", "suspect") and o["value"] is not None]
    latest = observations[-1] if observations else None
    latest_good = good[-1] if good else None
    if sensor.get("status") == "maintenance":
        state = "MAINTENANCE"
    elif latest is None:
        state = "NO_DATA"
    else:
        age = (ref - clock.parse(latest["observed_at"])).total_seconds()
        if age > fresh_cfg["offline_after_s"]:
            state = "OFFLINE"
        elif age > fresh_cfg["stale_multiplier"] * interval:
            state = "STALE"
        else:
            state = "FRESH"
    age_s = delay_s = None
    delayed = False
    if latest is not None:
        age_s = (ref - clock.parse(latest["observed_at"])).total_seconds()
        delay_s = (clock.parse(latest["received_at"]) - clock.parse(latest["observed_at"])).total_seconds()
        delayed = delay_s > fresh_cfg["delay_multiplier"] * interval
    return SensorHealth(
        sensor_id=sensor["id"],
        sensor_type=sensor["sensor_type"],
        label=sensor["label"],
        state=state,
        last_observed_at=latest["observed_at"] if latest else None,
        last_received_at=latest["received_at"] if latest else None,
        age_s=age_s,
        delay_s=delay_s,
        delayed=delayed,
        expected_interval_s=interval,
        latest_value=latest_good["value"] if latest_good else None,
        latest_quality=latest["quality_status"] if latest else None,
        latest_origin=latest["origin"] if latest else None,
        latest_observation_id=latest_good["id"] if latest_good else None,
    )


def _state_to_status(health: SensorHealth) -> str:
    return {"FRESH": "available", "STALE": "stale"}.get(health.state, "missing")


def _good(observations: list[dict]) -> list[dict]:
    return [o for o in observations if o["quality_status"] in ("good", "suspect") and o["value"] is not None]


def rain_accumulation(sensor: dict, observations: list[dict], health: SensorHealth, hours: int, cfg: dict, ref: datetime) -> Indicator:
    key = f"rain_{hours}h_mm"
    ind = Indicator(key, f"Rainfall, last {hours} h", "mm", None, "missing", sensor["id"], None)
    status = _state_to_status(health)
    if status == "missing":
        ind.notes.append(f"Rain gauge is {health.state.lower().replace('_', ' ')}; accumulation not computed.")
        return ind
    start = ref - timedelta(hours=hours)
    window = [o for o in _good(observations) if start < clock.parse(o["observed_at"]) <= ref]
    expected = max(1, int(hours * 3600 / int(sensor["expected_interval_s"])))
    coverage = min(1.0, len(window) / expected)
    ind.value = round(sum(o["value"] for o in window), 1)
    ind.coverage = round(coverage, 2)
    ind.evidence_ids = [o["id"] for o in window]
    ind.origins = {o["origin"] for o in window}
    ind.as_of = health.last_observed_at
    if not window:
        ind.status = "missing"
        ind.value = None
        ind.notes.append("No good-quality rainfall samples in the window.")
        return ind
    if status == "stale":
        ind.status = "stale"
        ind.notes.append("Gauge is stale: total covers data received so far and may be a lower bound.")
    elif coverage < cfg["rain"]["min_coverage"]:
        ind.status = "incomplete"
        ind.notes.append(f"Only {coverage:.0%} of expected samples present: total is a lower bound.")
    else:
        ind.status = "available"
    if any(o["quality_status"] == "suspect" for o in window):
        ind.notes.append("Window includes samples flagged 'suspect'.")
    return ind


def latest_value(sensor: dict, observations: list[dict], health: SensorHealth, key: str, label: str, unit: str) -> Indicator:
    ind = Indicator(key, label, unit, None, "missing", sensor["id"], None)
    status = _state_to_status(health)
    good = _good(observations)
    if status == "missing" or not good:
        ind.notes.append(f"Sensor is {health.state.lower().replace('_', ' ')}; no current reading.")
        return ind
    last = good[-1]
    ind.value = round(last["value"], 2)
    ind.as_of = last["observed_at"]
    ind.evidence_ids = [last["id"]]
    ind.origins = {last["origin"]}
    ind.status = status
    if status == "stale":
        ind.notes.append(f"Last reading is {_fmt_age(health.age_s)} old.")
    if last["quality_status"] == "suspect":
        ind.notes.append("Latest reading flagged 'suspect'.")
    return ind


def change_over(sensor: dict, observations: list[dict], health: SensorHealth, key: str, label: str, unit: str,
                hours: float, ref: datetime) -> Indicator:
    """Change between the latest reading and the reading closest to `hours` earlier."""
    ind = Indicator(key, label, unit, None, "missing", sensor["id"], None)
    status = _state_to_status(health)
    good = _good(observations)
    if status == "missing" or len(good) < 2:
        ind.notes.append(f"Sensor is {health.state.lower().replace('_', ' ')}; change not computed." if status == "missing"
                         else "Not enough readings to compute a change.")
        return ind
    last = good[-1]
    target = clock.parse(last["observed_at"]) - timedelta(hours=hours)
    tolerance = max(timedelta(hours=hours) * 0.25, timedelta(seconds=2 * int(sensor["expected_interval_s"])))
    earlier = min(good[:-1], key=lambda o: abs(clock.parse(o["observed_at"]) - target))
    gap = abs(clock.parse(earlier["observed_at"]) - target)
    if gap > tolerance:
        ind.notes.append(f"No reading near {hours:g} h before the latest one; change not computed.")
        return ind
    ind.value = round(last["value"] - earlier["value"], 2)
    ind.as_of = last["observed_at"]
    ind.evidence_ids = [earlier["id"], last["id"]]
    ind.origins = {earlier["origin"], last["origin"]}
    ind.status = status
    if status == "stale":
        ind.notes.append(f"Based on readings ending {_fmt_age(health.age_s)} ago.")
    return ind


def _fmt_age(seconds: float | None) -> str:
    if seconds is None:
        return "unknown"
    if seconds < 3600:
        return f"{int(seconds // 60)} min"
    return f"{seconds / 3600:.1f} h"


def build_features(sensors: list[dict], obs_by_sensor: dict[str, list[dict]], cfg: dict, ref: datetime | None = None) -> dict:
    """Compute indicators for a site.

    Returns {"indicators": {key: Indicator}, "health": {sensor_id: SensorHealth}}.
    """
    ref = ref or clock.now()
    indicators: dict[str, Indicator] = {}
    health: dict[str, SensorHealth] = {}
    by_type: dict[str, dict] = {}
    for s in sensors:
        if s.get("status") == "decommissioned":
            continue
        by_type.setdefault(s["sensor_type"], s)
        obs = sorted(obs_by_sensor.get(s["id"], []), key=lambda o: o["observed_at"])
        health[s["id"]] = sensor_health(s, obs, cfg, ref)

    def series(sensor: dict) -> list[dict]:
        return sorted(obs_by_sensor.get(sensor["id"], []), key=lambda o: o["observed_at"])

    rain = by_type.get("rain_gauge")
    if rain:
        h = health[rain["id"]]
        for hours in (1, 3, 24):
            ind = rain_accumulation(rain, series(rain), h, hours, cfg, ref)
            indicators[ind.key] = ind
    soil = by_type.get("soil_moisture")
    if soil:
        indicators["soil_moisture_pct"] = latest_value(
            soil, series(soil), health[soil["id"]], "soil_moisture_pct", "Soil moisture (volumetric)", "% VWC")
    ext = by_type.get("extensometer")
    if ext:
        indicators["displacement_24h_mm"] = change_over(
            ext, series(ext), health[ext["id"]], "displacement_24h_mm", "Slope displacement, 24 h change", "mm", 24, ref)
    river = by_type.get("river_stage")
    if river:
        indicators["river_level_m"] = latest_value(
            river, series(river), health[river["id"]], "river_level_m", "River stage", "m")
        indicators["river_rise_1h_m"] = change_over(
            river, series(river), health[river["id"]], "river_rise_1h_m", "River stage, 1 h change", "m", 1, ref)
    return {"indicators": indicators, "health": health}
