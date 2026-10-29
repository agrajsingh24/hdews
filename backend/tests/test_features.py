"""Feature extraction: windows, duplicates, ordering, freshness, quality and recovery."""
import math
from datetime import timedelta

from app import clock
from app.services.risk_engine import build_features, merge_config
from app.services.risk_engine.features import dedupe_readings
from tests.test_risk_engine import REF, SENSORS, normal, run, series

CFG = merge_config(None)


def feats(obs):
    return build_features(SENSORS, obs, CFG, REF)


def test_duplicate_timestamps_from_two_origins_are_not_double_counted():
    """HDEWS-003: an OBSERVED copy of a SIMULATED rain series doubled the accumulation."""
    obs = normal()
    sim = series(lambda h: 1.0)
    real = [{**o, "id": o["id"] + 500000, "origin": "OBSERVED"} for o in sim]
    obs["rain"] = sim + real
    f = feats(obs)
    assert f["indicators"]["rain_1h_mm"].value == 4.0
    assert f["indicators"]["rain_24h_mm"].value == 96.0
    assert f["indicators"]["rain_1h_mm"].origins == {"OBSERVED"}, "observed readings take precedence"
    assert f["health"]["rain"].duplicates_collapsed == len(sim)


def test_conflicting_duplicates_are_flagged_and_degrade_reliability():
    obs = normal()
    sim = series(lambda h: 25.0)
    obs["soil"] = sim + [{**sim[-1], "id": 999999, "origin": "OBSERVED", "value": 47.0}]
    r = run("landslide", obs)
    soil = next(f for f in r["factors"] if f["key"] == "soil_moisture_pct")
    assert soil["value"] == 47.0
    assert r["reliability"] == "DEGRADED"
    assert any("conflicting" in n for n in r["reliability_notes"])


def test_simulated_reading_never_replaces_an_observed_one_even_if_unusable():
    a = {"id": 1, "observed_at": "2026-07-15T11:45:00Z", "value": None, "quality_status": "bad", "origin": "OBSERVED"}
    b = {"id": 2, "observed_at": "2026-07-15T11:45:00Z", "value": 5.0, "quality_status": "good", "origin": "SIMULATED"}
    kept, collapsed, _ = dedupe_readings([b, a])
    assert kept == [a] and collapsed == 1


def test_out_of_order_input_gives_same_result_as_ordered():
    obs = normal()
    obs["river"] = series(lambda h: 2.0 + (0.5 if h < 1 else 0))
    ordered = feats(obs)["indicators"]
    obs["river"] = list(reversed(obs["river"]))
    shuffled = feats(obs)["indicators"]
    for k in ordered:
        assert ordered[k].value == shuffled[k].value and ordered[k].status == shuffled[k].status


def test_rolling_window_boundaries():
    """A reading exactly at window start is excluded; one exactly at the reference time is included."""
    rain = {"id": 1, "expected_interval_s": 900}
    obs = normal()
    obs["rain"] = [
        {"id": 10, "value": 7.0, "observed_at": clock.iso(REF - timedelta(hours=1)), "received_at": clock.iso(REF), "quality_status": "good", "origin": "SIMULATED"},
        {"id": 11, "value": 3.0, "observed_at": clock.iso(REF), "received_at": clock.iso(REF), "quality_status": "good", "origin": "SIMULATED"},
    ]
    ind = feats(obs)["indicators"]
    assert ind["rain_1h_mm"].value == 3.0
    assert ind["rain_3h_mm"].value == 10.0
    assert ind["rain_1h_mm"].status == "incomplete"  # 1 of 4 expected samples
    del rain


def test_empty_window_and_no_data():
    obs = normal()
    obs["rain"] = []
    ind = feats(obs)["indicators"]
    assert all(ind[k].status == "missing" and ind[k].value is None for k in ("rain_1h_mm", "rain_3h_mm", "rain_24h_mm"))
    assert feats(obs)["health"]["rain"].state == "NO_DATA"


def test_insufficient_rain_history_is_incomplete_not_low():
    obs = normal()
    obs["rain"] = series(lambda h: 0.0, hours=2)  # gauge only installed 2 h ago
    ind = feats(obs)["indicators"]
    assert ind["rain_1h_mm"].status == "available"
    assert ind["rain_24h_mm"].status == "incomplete" and ind["rain_24h_mm"].coverage < 0.75


def test_reporting_sensor_with_only_unusable_recent_readings_is_not_current():
    """HDEWS-008: a sensor sending bad readings made a 5 h old value look current."""
    obs = normal()
    old = series(lambda h: 45.0, end_offset_min=300)
    bad = series(lambda h: 0.0, hours=4)
    for o in bad:
        o["quality_status"] = "bad"
    obs["soil"] = old + bad
    f = feats(obs)
    assert f["health"]["soil"].state == "FRESH" and f["health"]["soil"].usable_state == "STALE"
    soil = f["indicators"]["soil_moisture_pct"]
    assert soil.status == "stale" and soil.value == 45.0
    r = run("landslide", obs)
    assert r["reliability"] == "POOR" and r["risk_tier"] != "LOW"
    assert any("unusable" in n for n in r["reliability_notes"])


def test_non_finite_readings_are_excluded():
    obs = normal()
    obs["soil"] = series(lambda h: 25.0)
    obs["soil"][-1] = {**obs["soil"][-1], "value": math.nan}
    obs["soil"][-2] = {**obs["soil"][-2], "value": math.inf}
    ind = feats(obs)["indicators"]["soil_moisture_pct"]
    assert ind.value == 25.0 and math.isfinite(ind.value)


def test_recovery_after_outage_requires_new_readings():
    obs = normal()
    obs["soil"] = series(lambda h: 25.0, hours=30, end_offset_min=8 * 60)
    assert run("landslide", obs)["risk_tier"] == "INSUFFICIENT_DATA"
    obs["soil"] = obs["soil"] + series(lambda h: 25.0, hours=0.5)
    r = run("landslide", obs)
    assert r["risk_tier"] == "LOW" and r["reliability"] == "GOOD"


def test_maintenance_sensor_is_unavailable():
    sensors = [{**s, "status": "maintenance"} if s["id"] == "soil" else s for s in SENSORS]
    f = build_features(sensors, normal(), CFG, REF)
    assert f["health"]["soil"].state == "MAINTENANCE"
    assert f["indicators"]["soil_moisture_pct"].status == "missing"


def test_decommissioned_sensor_is_ignored():
    sensors = [{**s, "status": "decommissioned"} if s["id"] == "ext" else s for s in SENSORS]
    f = build_features(sensors, normal(), CFG, REF)
    assert "displacement_24h_mm" not in f["indicators"] and "ext" not in f["health"]


def test_change_needs_reading_near_target_time():
    obs = normal()
    obs["ext"] = series(lambda h: 10.0, hours=3)  # no reading near 24 h ago
    ind = feats(obs)["indicators"]["displacement_24h_mm"]
    assert ind.status == "missing" and "No reading near" in ind.notes[0]


def test_timestamps_with_offsets_compare_correctly():
    """Readings stored in UTC; an IST-offset reference time must be interpreted as the same instant."""
    ist = clock.parse("2026-07-15T17:30:00+05:30")
    assert ist == REF
    obs = normal()
    a = build_features(SENSORS, obs, CFG, ist)["indicators"]["rain_1h_mm"]
    b = feats(obs)["indicators"]["rain_1h_mm"]
    assert a.value == b.value and a.coverage == b.coverage


def test_reporting_sensor_whose_usable_data_is_hours_old_is_missing_with_clear_note():
    obs = normal()
    old = series(lambda h: 30.0, hours=30, end_offset_min=8 * 60)
    bad = series(lambda h: 0.0, hours=2)
    for o in bad:
        o["quality_status"] = "bad"
    obs["soil"] = old + bad
    f = feats(obs)
    assert f["health"]["soil"].state == "FRESH" and f["health"]["soil"].usable_state == "OFFLINE"
    ind = f["indicators"]["soil_moisture_pct"]
    assert ind.status == "missing" and "reporting, but its recent readings are unusable" in ind.notes[0]


def test_suspect_samples_are_used_but_noted():
    obs = normal()
    obs["soil"] = series(lambda h: 26.0)
    obs["soil"][-1] = {**obs["soil"][-1], "quality_status": "suspect"}
    obs["rain"] = series(lambda h: 0.5)
    obs["rain"][-1] = {**obs["rain"][-1], "quality_status": "suspect"}
    ind = feats(obs)["indicators"]
    assert any("suspect" in n for n in ind["soil_moisture_pct"].notes)
    assert any("suspect" in n for n in ind["rain_1h_mm"].notes)


def test_single_reading_cannot_produce_a_change():
    obs = normal()
    obs["ext"] = series(lambda h: 10.0, hours=0)
    ind = feats(obs)["indicators"]["displacement_24h_mm"]
    assert ind.status == "missing" and "Not enough readings" in ind.notes[0]
