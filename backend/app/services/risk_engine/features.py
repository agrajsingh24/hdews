"""Feature extraction: turn raw sensor observations into indicators with explicit
freshness, coverage, quality and provenance.

An indicator `status` is one of:
  available   - computed from fresh, sufficiently complete, good-quality data
  incomplete  - computed, but from fewer samples than expected (value is a lower bound for sums)
  stale       - sensor has not reported recently; value reflects the last data received
  missing     - no usable data (no sensor, offline beyond the limit, or no good samples)
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from ... import clock


# When the same sensor has several readings at the same observed time (e.g. a simulated and an
# observed reading), only one may count. Real measurements take precedence over imported or
# generated ones; summing both would double-count rainfall (bug HDEWS-003).
ORIGIN_PRECEDENCE = {"OBSERVED": 0, "IMPORTED": 1, "DERIVED": 2, "SIMULATED": 3}


def is_usable(o: dict) -> bool:
    """A reading can be used as evidence: acceptable quality and a finite numeric value."""
    v = o.get("value")
    return (o.get("quality_status") in ("good", "suspect") and v is not None
            and isinstance(v, (int, float)) and math.isfinite(v))


def dedupe_readings(observations: list[dict]) -> tuple[list[dict], int, int]:
    """Collapse readings sharing an observed time. Returns (readings sorted by time, collapsed, conflicts).

    `conflicts` counts timestamps where the collapsed readings disagreed in value.
    """
    by_time: dict[str, list[dict]] = {}
    for o in observations:
        by_time.setdefault(o["observed_at"], []).append(o)
    out, collapsed, conflicts = [], 0, 0
    for t in sorted(by_time):
        group = by_time[t]
        if len(group) > 1:
            collapsed += len(group) - 1
            usable_values = {round(o["value"], 6) for o in group if is_usable(o)}
            if len(usable_values) > 1:
                conflicts += 1
            # Origin first: a simulated reading must never stand in for a real one, even an unusable one.
            group.sort(key=lambda o: (ORIGIN_PRECEDENCE.get(o.get("origin"), 9), 0 if is_usable(o) else 1, o.get("id") or 0))
        out.append(group[0])
    return out, collapsed, conflicts


def single_origin(observations: list[dict]) -> tuple[list[dict], str | None, int]:
    """Keep only the readings of one origin for a sensor. Returns (kept, origin used, readings ignored).

    Readings from different origins (e.g. a real gateway and the simulator) describe different
    series: summing them double-counts rain, and differencing them (24 h displacement, 1 h river
    rise) yields a meaningless number that can raise a false HIGH or hide a real rise (HDEWS-033).
    The highest-precedence origin present is used (observed > imported > derived > simulated), the
    same rule as for same-timestamp duplicates, so a simulated series never stands in for a real one.
    """
    origins = {o.get("origin") for o in observations}
    if len(origins) <= 1:
        return observations, next(iter(origins), None), 0
    primary = min(origins, key=lambda x: ORIGIN_PRECEDENCE.get(x, 9))
    kept = [o for o in observations if o.get("origin") == primary]
    return kept, primary, len(observations) - len(kept)


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
    # Freshness of the newest *usable* reading. A sensor can be reporting (state FRESH) while all
    # recent readings are unusable; indicators must then not present an old value as current.
    usable_state: str = "NO_DATA"
    last_usable_observed_at: str | None = None
    duplicates_collapsed: int = 0
    conflicting_duplicates: int = 0
    # Readings of another origin ignored because the sensor also has readings of a higher-precedence origin.
    origin_used: str | None = None
    other_origin_readings_ignored: int = 0

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


def _freshness(observed_at: str | None, interval: int, fresh_cfg: dict, ref: datetime) -> str:
    if observed_at is None:
        return "NO_DATA"
    age = (ref - clock.parse(observed_at)).total_seconds()
    if age > fresh_cfg["offline_after_s"]:
        return "OFFLINE"
    if age > fresh_cfg["stale_multiplier"] * interval:
        return "STALE"
    return "FRESH"


def sensor_health(sensor: dict, observations: list[dict], cfg: dict, ref: datetime,
                  collapsed: int = 0, conflicts: int = 0) -> SensorHealth:
    interval = int(sensor["expected_interval_s"])
    fresh_cfg = cfg["freshness"]
    good = [o for o in observations if is_usable(o)]
    latest = observations[-1] if observations else None
    latest_good = good[-1] if good else None
    if sensor.get("status") == "maintenance":
        state = usable_state = "MAINTENANCE"
    else:
        state = _freshness(latest["observed_at"] if latest else None, interval, fresh_cfg, ref)
        usable_state = _freshness(latest_good["observed_at"] if latest_good else None, interval, fresh_cfg, ref)
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
        usable_state=usable_state,
        last_usable_observed_at=latest_good["observed_at"] if latest_good else None,
        duplicates_collapsed=collapsed,
        conflicting_duplicates=conflicts,
    )


def _state_to_status(health: SensorHealth) -> str:
    # Indicator freshness follows the newest usable reading, not merely the newest message.
    return {"FRESH": "available", "STALE": "stale"}.get(health.usable_state, "missing")


def _good(observations: list[dict]) -> list[dict]:
    return [o for o in observations if is_usable(o)]


def _unavailable_note(health: SensorHealth) -> str:
    if health.state == "FRESH" and health.usable_state != "FRESH":
        return "Sensor is reporting, but its recent readings are unusable (bad quality, missing or non-finite values)"
    return f"Sensor is {health.state.lower().replace('_', ' ')}"


def rain_accumulation(sensor: dict, observations: list[dict], health: SensorHealth, hours: int, cfg: dict, ref: datetime) -> Indicator:
    key = f"rain_{hours}h_mm"
    ind = Indicator(key, f"Rainfall, last {hours} h", "mm", None, "missing", sensor["id"], None)
    status = _state_to_status(health)
    if status == "missing":
        ind.notes.append(f"{_unavailable_note(health)}; accumulation not computed.")
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
        ind.notes.append(f"{_unavailable_note(health)}; no current reading.")
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
        ind.notes.append(f"{_unavailable_note(health)}; change not computed." if status == "missing"
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
    clean: dict[str, list[dict]] = {}
    for s in sensors:
        if s.get("status") == "decommissioned":
            continue
        by_type.setdefault(s["sensor_type"], s)
        obs, collapsed, conflicts = dedupe_readings(obs_by_sensor.get(s["id"], []))
        obs, origin_used, ignored = single_origin(obs)
        clean[s["id"]] = obs
        health[s["id"]] = sensor_health(s, obs, cfg, ref, collapsed, conflicts)
        health[s["id"]].origin_used = origin_used
        health[s["id"]].other_origin_readings_ignored = ignored

    def series(sensor: dict) -> list[dict]:
        return clean[sensor["id"]]

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
