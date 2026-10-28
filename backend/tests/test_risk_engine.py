"""Unit tests for the baseline risk engine (no database)."""
from datetime import datetime, timedelta, timezone

import pytest

from app import clock
from app.services.risk_engine import MLModelInterface, assess, build_features, merge_config, validate_site_overrides

REF = datetime(2026, 7, 15, 12, 0, tzinfo=timezone.utc)
SITE = {"id": "S1", "name": "Test site"}

SENSORS = [
    {"id": "rain", "sensor_type": "rain_gauge", "label": "Rain gauge", "expected_interval_s": 900, "status": "active"},
    {"id": "soil", "sensor_type": "soil_moisture", "label": "Soil moisture", "expected_interval_s": 900, "status": "active"},
    {"id": "ext", "sensor_type": "extensometer", "label": "Extensometer", "expected_interval_s": 900, "status": "active"},
    {"id": "river", "sensor_type": "river_stage", "label": "River stage", "expected_interval_s": 900, "status": "active"},
]

_ids = iter(range(1, 10**6))


def series(fn, hours=26, step_min=15, end_offset_min=0, delay_min=0, origin="SIMULATED", quality="good"):
    """Build observations ending `end_offset_min` before REF. fn(hours_before_ref) -> value."""
    out = []
    end = REF - timedelta(minutes=end_offset_min)
    t = end - timedelta(hours=hours)
    while t <= end:
        h_before = (REF - t).total_seconds() / 3600
        out.append({
            "id": next(_ids), "value": fn(h_before), "observed_at": clock.iso(t),
            "received_at": clock.iso(t + timedelta(minutes=delay_min)),
            "quality_status": quality, "origin": origin,
        })
        t += timedelta(minutes=step_min)
    return out


def run(hazard, obs, cfg_overrides=None, sensors=SENSORS, previous=None):
    cfg = merge_config(cfg_overrides)
    feats = build_features(sensors, obs, cfg, REF)
    return assess(SITE, hazard, feats["indicators"], feats["health"], cfg, REF, previous)


def normal():
    return {
        "rain": series(lambda h: 0.0),
        "soil": series(lambda h: 25.0),
        "ext": series(lambda h: 10.0),
        "river": series(lambda h: 1.5),
    }


def test_normal_conditions_are_low_with_good_reliability():
    for hazard in ("landslide", "flash_flood"):
        r = run(hazard, normal())
        assert r["risk_tier"] == "LOW"
        assert r["reliability"] == "GOOD"
        assert r["score"] == 0
        assert r["missing_inputs"] == []
        assert r["threshold_status"].startswith("EXPERIMENTAL")


def test_heavy_rain_wet_soil_and_movement_gives_high_landslide():
    obs = normal()
    obs["rain"] = series(lambda h: 2.0)          # 8 mm/h for 26 h -> ~192 mm/24h, 8 mm/1h
    obs["soil"] = series(lambda h: 46.0)         # +18 over baseline 28
    obs["ext"] = series(lambda h: 20.0 - h * 0.3)  # ~7.2 mm over 24 h
    r = run("landslide", obs)
    assert r["risk_tier"] == "HIGH"
    assert r["reliability"] == "GOOD"
    levels = {f["key"]: f["level"] for f in r["factors"]}
    assert levels["rain_24h_mm"] == "high"
    assert levels["soil_moisture_pct"] == "high"
    assert levels["displacement_24h_mm"] == "high"
    assert set(r["contributing_factors"]) >= {"rain_24h_mm", "soil_moisture_pct", "displacement_24h_mm"}
    assert r["evidence_observation_ids"], "assessment must reference evidence"


def test_rain_accumulation_is_computed_correctly():
    obs = normal()
    obs["rain"] = series(lambda h: 1.0)  # 4 samples/h
    cfg = merge_config(None)
    feats = build_features(SENSORS, obs, cfg, REF)
    ind = feats["indicators"]
    assert ind["rain_1h_mm"].value == 4.0
    assert ind["rain_3h_mm"].value == 12.0
    assert ind["rain_24h_mm"].value == 96.0
    assert ind["rain_24h_mm"].coverage == 1.0


def test_rising_river_gives_high_flash_flood():
    obs = normal()
    obs["river"] = series(lambda h: 4.4 - h * 0.7 if h < 2 else 3.0)  # above danger, rising 0.7 m/h
    obs["rain"] = series(lambda h: 6.0 if h < 3 else 0.0)  # 24 mm/h
    r = run("flash_flood", obs)
    assert r["risk_tier"] == "HIGH"
    levels = {f["key"]: f["level"] for f in r["factors"]}
    assert levels["river_level_m"] == "high"
    assert levels["river_rise_1h_m"] == "high"


def test_missing_critical_input_never_reports_low():
    obs = normal()
    obs["soil"] = []  # critical for landslide
    r = run("landslide", obs)
    assert r["reliability"] == "POOR"
    assert r["risk_tier"] == "INSUFFICIENT_DATA"
    assert any(m["key"] == "soil_moisture_pct" and m["critical"] for m in r["missing_inputs"])
    assert "insufficient data" in r["summary"].lower()


def test_offline_sensor_during_heavy_rain_keeps_elevated_as_lower_bound():
    obs = normal()
    obs["rain"] = series(lambda h: 2.5)                            # ~240 mm / 24 h
    obs["soil"] = series(lambda h: 40.0, hours=30, end_offset_min=8 * 60)  # offline > 6 h
    r = run("landslide", obs)
    assert r["reliability"] == "POOR"
    assert r["risk_tier"] in ("ELEVATED", "HIGH")
    assert r["tier_is_lower_bound"] is True
    assert r["max_possible_tier"] == "HIGH"
    soil = next(f for f in r["factors"] if f["key"] == "soil_moisture_pct")
    assert soil["status"] == "missing" and soil["points"] == 0


def test_stale_sensor_is_flagged_not_presented_as_current():
    obs = normal()
    obs["river"] = series(lambda h: 1.5, end_offset_min=90)  # 90 min > 3 x 15 min
    cfg = merge_config(None)
    feats = build_features(SENSORS, obs, cfg, REF)
    assert feats["health"]["river"].state == "STALE"
    r = assess(SITE, "flash_flood", feats["indicators"], feats["health"], cfg, REF)
    river = next(f for f in r["factors"] if f["key"] == "river_level_m")
    assert river["status"] == "stale"
    assert r["reliability"] == "POOR"
    assert r["risk_tier"] == "INSUFFICIENT_DATA"


def test_delayed_observations_degrade_reliability():
    obs = normal()
    obs["soil"] = series(lambda h: 25.0, end_offset_min=0, delay_min=40)
    r = run("landslide", obs)
    assert r["reliability"] == "DEGRADED"
    assert any("arrived" in n for n in r["reliability_notes"])


def test_incomplete_rain_coverage_is_degraded():
    obs = normal()
    obs["rain"] = [o for i, o in enumerate(series(lambda h: 0.5)) if i % 2 == 0]  # half the samples
    r = run("landslide", obs)
    rain24 = next(f for f in r["factors"] if f["key"] == "rain_24h_mm")
    assert rain24["status"] == "incomplete"
    assert r["reliability"] == "DEGRADED"


def test_bad_quality_readings_are_excluded():
    obs = normal()
    obs["soil"] = series(lambda h: 25.0)
    obs["soil"][-1] = {**obs["soil"][-1], "value": 99.0, "quality_status": "bad"}
    feats = build_features(SENSORS, obs, merge_config(None), REF)
    assert feats["indicators"]["soil_moisture_pct"].value == 25.0


def test_site_specific_thresholds_change_outcome():
    obs = normal()
    obs["soil"] = series(lambda h: 36.0)  # +8 over default baseline -> watch
    r_default = run("landslide", obs)
    r_site = run("landslide", obs, {"landslide": {"soil_moisture_baseline_pct": 34.0}})
    lvl = lambda r: next(f for f in r["factors"] if f["key"] == "soil_moisture_pct")["level"]
    assert lvl(r_default) == "watch"
    assert lvl(r_site) == "normal"


def test_changes_since_previous_assessment():
    first = run("landslide", normal())
    obs = normal()
    obs["soil"] = []
    second = run("landslide", obs, previous=first)
    assert any("LOW → INSUFFICIENT_DATA" in i for i in second["changes"]["items"])


def test_missing_sensor_type_is_reported():
    sensors = [s for s in SENSORS if s["id"] != "ext"]
    obs = normal()
    r = run("landslide", obs, sensors=sensors)
    ext = next(f for f in r["factors"] if f["key"] == "displacement_24h_mm")
    assert ext["status"] == "missing"
    assert r["reliability"] == "DEGRADED"  # non-critical input missing
    assert r["risk_tier"] == "LOW"


def test_threshold_validation():
    assert validate_site_overrides({"landslide": {"rain_24h_mm": {"watch": 50, "high": 100}}}) == []
    assert validate_site_overrides({"landslide": {"rain_24h_mm": {"watch": 120, "high": 100}}})
    assert validate_site_overrides({"flash_flood": {"river_warning_level_m": 5, "river_danger_level_m": 4}})
    assert validate_site_overrides({"bogus": {}})


def test_unvalidated_ml_model_cannot_be_registered():
    class Model:
        name, version, validated = "rf", "0", False
    with pytest.raises(ValueError):
        MLModelInterface.register("landslide", Model())
