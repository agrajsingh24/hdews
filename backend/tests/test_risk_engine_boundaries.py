"""Risk-engine validation: threshold boundaries, safety invariants and randomised property checks.

Indicators are constructed directly so each rule is tested in isolation from feature extraction.
Hypothesis is not installed in this environment (no package index access); the property checks
below use seeded `random` generators instead, so failures are reproducible.
"""
import math
import random
from datetime import datetime, timezone

import pytest

from app.services.risk_engine import DEFAULT_CONFIG, assess, merge_config
from app.services.risk_engine.engine import TIER_ORDER, tier_for_score
from app.services.risk_engine.features import Indicator, SensorHealth
from app.services.risk_engine.rules import RULES

REF = datetime(2026, 7, 15, 12, 0, tzinfo=timezone.utc)
AS_OF = "2026-07-15T12:00:00Z"
SITE = {"id": "S", "name": "Site"}
SENSOR_OF = {"rain_1h_mm": "rain", "rain_3h_mm": "rain", "rain_24h_mm": "rain", "soil_moisture_pct": "soil",
             "displacement_24h_mm": "ext", "river_level_m": "river", "river_rise_1h_m": "river"}
BENIGN = {"rain_1h_mm": 0.0, "rain_3h_mm": 0.0, "rain_24h_mm": 0.0, "soil_moisture_pct": 25.0,
          "displacement_24h_mm": 0.0, "river_level_m": 1.0, "river_rise_1h_m": 0.0}

_ids = iter(range(1, 10**9))


def ind(key, value, status="available"):
    return Indicator(key, key, "u", value, status, SENSOR_OF[key], AS_OF if value is not None else None,
                     evidence_ids=[next(_ids)] if value is not None else [], origins={"SIMULATED"})


def health():
    return {s: SensorHealth(s, s, s, "FRESH", AS_OF, AS_OF, 0, 0, False, 900, 1.0, "good", "SIMULATED", 1,
                            usable_state="FRESH", last_usable_observed_at=AS_OF)
            for s in ("rain", "soil", "ext", "river")}


def run(hazard, values=None, statuses=None, cfg=None, drop=()):
    values = {**BENIGN, **(values or {})}
    statuses = statuses or {}
    indicators = {k: ind(k, v, statuses.get(k, "available")) for k, v in values.items() if k not in drop}
    return assess(SITE, hazard, indicators, health(), cfg or merge_config(None), REF)


def factor(result, key):
    return next(f for f in result["factors"] if f["key"] == key)


# ---------------------------------------------------------------- thresholds
def _threshold_cases():
    ls, ff = DEFAULT_CONFIG["landslide"], DEFAULT_CONFIG["flash_flood"]
    base = ls["soil_moisture_baseline_pct"]
    cases = []
    for hazard, key, watch, high, offset in [
        ("landslide", "rain_24h_mm", ls["rain_24h_mm"]["watch"], ls["rain_24h_mm"]["high"], 0),
        ("landslide", "rain_1h_mm", ls["rain_1h_mm"]["watch"], ls["rain_1h_mm"]["high"], 0),
        ("landslide", "soil_moisture_pct", ls["soil_moisture_excess_pct"]["watch"], ls["soil_moisture_excess_pct"]["high"], base),
        ("landslide", "displacement_24h_mm", ls["displacement_24h_mm"]["watch"], ls["displacement_24h_mm"]["high"], 0),
        ("flash_flood", "river_level_m", ff["river_warning_level_m"], ff["river_danger_level_m"], 0),
        ("flash_flood", "river_rise_1h_m", ff["river_rise_1h_m"]["watch"], ff["river_rise_1h_m"]["high"], 0),
        ("flash_flood", "rain_1h_mm", ff["rain_1h_mm"]["watch"], ff["rain_1h_mm"]["high"], 0),
        ("flash_flood", "rain_3h_mm", ff["rain_3h_mm"]["watch"], ff["rain_3h_mm"]["high"], 0),
    ]:
        rule = next(r for r in RULES[hazard] if r.key == key)
        eps = 0.01
        cases += [
            (hazard, key, offset + watch - eps, "normal", 0),
            (hazard, key, offset + watch, "watch", rule.watch_points),
            (hazard, key, offset + watch + eps, "watch", rule.watch_points),
            (hazard, key, offset + high - eps, "watch", rule.watch_points),
            (hazard, key, offset + high, "high", rule.high_points),
            (hazard, key, offset + high + eps, "high", rule.high_points),
        ]
    return cases


@pytest.mark.parametrize("hazard,key,value,level,points", _threshold_cases())
def test_threshold_boundaries(hazard, key, value, level, points):
    """Below / exactly at / above every documented demo threshold."""
    r = run(hazard, {key: value})
    f = factor(r, key)
    assert (f["level"], f["points"]) == (level, points)
    assert r["score"] == points
    assert r["risk_tier"] == tier_for_score(points, DEFAULT_CONFIG)


def test_tier_score_boundaries():
    cfg = DEFAULT_CONFIG
    assert [tier_for_score(s, cfg) for s in range(0, 6)] == ["LOW", "LOW", "ELEVATED", "ELEVATED", "HIGH", "HIGH"]


def test_multiple_adverse_indicators_combine():
    r = run("landslide", {"rain_24h_mm": 60, "rain_1h_mm": 16, "soil_moisture_pct": 37})  # 1 + 1 + 1
    assert r["score"] == 3 and r["risk_tier"] == "ELEVATED"
    assert set(r["contributing_factors"]) == {"rain_24h_mm", "rain_1h_mm", "soil_moisture_pct"}


def test_severe_single_indicator_reaches_high():
    assert run("landslide", {"displacement_24h_mm": 9})["risk_tier"] == "HIGH"
    assert run("flash_flood", {"river_level_m": 4.5})["risk_tier"] == "HIGH"


def test_very_large_values_are_handled():
    r = run("flash_flood", {"rain_1h_mm": 1e6, "rain_3h_mm": 1e7, "river_level_m": 1e3, "river_rise_1h_m": 50})
    assert r["risk_tier"] == "HIGH" and r["score"] == 10


def test_negative_change_values_are_normal_not_errors():
    r = run("flash_flood", {"river_rise_1h_m": -0.8})
    assert factor(r, "river_rise_1h_m")["level"] == "normal"


# ---------------------------------------------------------------- invariants
def test_inv1_tier_and_reliability_are_separate_fields():
    r = run("landslide", {"rain_24h_mm": 120}, statuses={"soil_moisture_pct": "stale"})
    assert r["risk_tier"] in TIER_ORDER and r["reliability"] in ("GOOD", "DEGRADED", "POOR")
    assert r["risk_tier"] != r["reliability"]


@pytest.mark.parametrize("hazard,critical", [("landslide", "rain_24h_mm"), ("landslide", "soil_moisture_pct"),
                                             ("flash_flood", "river_level_m"), ("flash_flood", "rain_1h_mm")])
@pytest.mark.parametrize("how", ["missing", "stale-benign"])
def test_inv2_inv3_missing_or_stale_critical_with_benign_rest_is_insufficient_data(hazard, critical, how):
    if how == "missing":
        r = run(hazard, {critical: None}, statuses={critical: "missing"})
    else:
        r = run(hazard, statuses={critical: "stale"})  # stale benign value
    assert r["reliability"] == "POOR"
    assert r["risk_tier"] == "INSUFFICIENT_DATA", "missing/stale critical data must never read as LOW"
    assert any(m["key"] == critical and m["critical"] for m in r["missing_inputs"])


def test_inv4_adverse_evidence_is_kept_and_underestimate_disclosed():
    r = run("landslide", {"rain_24h_mm": 150, "soil_moisture_pct": None}, statuses={"soil_moisture_pct": "missing"})
    assert r["risk_tier"] == "ELEVATED" and r["reliability"] == "POOR"
    assert r["tier_is_lower_bound"] is True and r["max_possible_tier"] == "HIGH"
    assert "understate" in r["summary"]


def test_inv6_score_is_never_presented_as_probability():
    r = run("landslide", {"rain_24h_mm": 150})
    assert "not a probability" in r["score_note"]
    assert not any("probab" in k for k in r)


def test_inv7_rule_version_and_time_present():
    r = run("flash_flood")
    assert r["rule_version"] == "baseline-rules-v0.1-demo"
    assert r["assessed_at"] == "2026-07-15T12:00:00Z"
    assert r["threshold_status"].startswith("EXPERIMENTAL")


def test_inv8_every_contributing_factor_has_evidence_and_ids_match():
    r = run("landslide", {"rain_24h_mm": 150, "displacement_24h_mm": 3})
    for f in r["factors"]:
        if f["points"] > 0:
            assert f["evidence_ids"], f"{f['key']} contributes without evidence"
    assert set(r["evidence_observation_ids"]) == {i for f in r["factors"] for i in f["evidence_ids"]}


def test_inv9_threshold_change_changes_outcome_consistently():
    cfg = merge_config({"landslide": {"rain_24h_mm": {"watch": 10, "high": 20}}})
    assert factor(run("landslide", {"rain_24h_mm": 25}), "rain_24h_mm")["level"] == "normal"
    assert factor(run("landslide", {"rain_24h_mm": 25}, cfg=cfg), "rain_24h_mm")["level"] == "high"


def test_inv10_deterministic_for_identical_inputs():
    a = run("landslide", {"rain_24h_mm": 70, "soil_moisture_pct": 40})
    b = run("landslide", {"rain_24h_mm": 70, "soil_moisture_pct": 40})
    strip = lambda r: {k: v for k, v in r.items() if k not in ("evidence_observation_ids", "factors")}
    assert strip(a) == strip(b)
    assert [(f["key"], f["level"], f["points"]) for f in a["factors"]] == [(f["key"], f["level"], f["points"]) for f in b["factors"]]


def test_inv11_outage_of_decisive_sensor_cannot_lower_apparent_risk():
    """HDEWS-009: HIGH from slope movement must not become LOW when the extensometer goes offline."""
    high = run("landslide", {"displacement_24h_mm": 7})
    assert high["risk_tier"] == "HIGH"
    outage = run("landslide", {"displacement_24h_mm": None}, statuses={"displacement_24h_mm": "missing"})
    assert outage["risk_tier"] != "LOW"
    assert outage["risk_tier"] == "INSUFFICIENT_DATA" and outage["reliability"] == "POOR"
    f = factor(outage, "displacement_24h_mm")
    assert f["critical"] and "could change the tier" in f["critical_reason"]


def test_inv11_unconfigured_sensor_is_not_treated_as_outage():
    """A site with no extensometer keeps the documented DEGRADED behaviour (not an outage)."""
    r = run("landslide", drop=("displacement_24h_mm",))
    assert r["risk_tier"] == "LOW" and r["reliability"] == "DEGRADED"
    assert factor(r, "displacement_24h_mm")["critical"] is False


def test_lower_bound_only_claimed_when_missing_inputs_can_raise_tier():
    """HDEWS-011: score 2 (ELEVATED) + one incomplete input worth at most +1 cannot reach HIGH."""
    r = run("flash_flood", {"rain_1h_mm": 10, "rain_3h_mm": 31, "river_rise_1h_m": 0.35},
            statuses={"rain_3h_mm": "incomplete"})
    assert r["risk_tier"] == "ELEVATED" and r["max_possible_tier"] == "ELEVATED"
    assert r["tier_is_lower_bound"] is False
    assert "understate" not in r["summary"]


def test_non_finite_indicator_values_are_never_scored_normal():
    """HDEWS-010: NaN compared with a threshold is False, which used to read as 'normal'."""
    for bad in (math.nan, math.inf, -math.inf):
        r = run("landslide", {"soil_moisture_pct": bad})
        f = factor(r, "soil_moisture_pct")
        assert f["level"] != "normal" and f["status"] == "missing"
        assert r["risk_tier"] == "INSUFFICIENT_DATA"


def test_suspect_quality_degrades_reliability():
    h = health()
    h["soil"].latest_quality = "suspect"
    indicators = {k: ind(k, v) for k, v in BENIGN.items()}
    r = assess(SITE, "landslide", indicators, h, merge_config(None), REF)
    assert r["reliability"] == "DEGRADED"


def test_unknown_hazard_rejected():
    with pytest.raises(ValueError):
        assess(SITE, "earthquake", {}, {}, merge_config(None), REF)


# ---------------------------------------------------------------- randomised properties
STATUSES = ["available", "available", "available", "stale", "incomplete", "missing"]


def _random_case(rng):
    hazard = rng.choice(["landslide", "flash_flood"])
    values, statuses = {}, {}
    for key in BENIGN:
        status = rng.choice(STATUSES)
        statuses[key] = status
        values[key] = None if status == "missing" else rng.choice([0.0, rng.uniform(0, 200), rng.uniform(0, 8)])
    return hazard, values, statuses


@pytest.mark.parametrize("seed", range(20))
def test_property_safety_invariants_hold_for_random_inputs(seed):
    rng = random.Random(seed)
    for _ in range(100):
        hazard, values, statuses = _random_case(rng)
        r = run(hazard, values, statuses)
        crit_unavailable = [f for f in r["factors"] if f["critical"] and f["status"] in ("missing", "stale")]
        # Missing/stale critical data never yields LOW.
        if crit_unavailable:
            assert r["reliability"] == "POOR" and r["risk_tier"] != "LOW"
        # Reliability is GOOD only if every input is available.
        if r["reliability"] == "GOOD":
            assert all(f["status"] == "available" for f in r["factors"])
        # The reported tier never exceeds the worst case, and the tier matches the score unless data is insufficient.
        if r["risk_tier"] != "INSUFFICIENT_DATA":
            assert r["risk_tier"] == tier_for_score(r["score"], DEFAULT_CONFIG)
            assert TIER_ORDER[r["max_possible_tier"]] >= TIER_ORDER[r["risk_tier"]]
        # Score equals the sum of factor points; points never exceed a factor's maximum.
        assert r["score"] == sum(f["points"] for f in r["factors"])
        assert all(0 <= f["points"] <= f["max_points"] for f in r["factors"])
        # Contributing factors always carry evidence.
        assert all(f["evidence_ids"] for f in r["factors"] if f["points"] > 0)


@pytest.mark.parametrize("seed", range(10))
def test_property_making_an_input_unavailable_never_lowers_the_tier(seed):
    """Invariant 11, randomised: taking any configured input offline must not lower the apparent risk."""
    rng = random.Random(1000 + seed)
    for _ in range(100):
        hazard = rng.choice(["landslide", "flash_flood"])
        values = {k: rng.choice([BENIGN[k], rng.uniform(0, 150), rng.uniform(0, 8)]) for k in BENIGN}
        before = run(hazard, values)
        key = rng.choice([r.key for r in RULES[hazard]])
        after = run(hazard, {**values, key: None}, {key: "missing"})
        assert not (before["risk_tier"] != "LOW" and after["risk_tier"] == "LOW"), (hazard, key, values)
        if after["risk_tier"] != "INSUFFICIENT_DATA":
            assert TIER_ORDER[after["max_possible_tier"]] >= TIER_ORDER[before["risk_tier"]]


def test_change_summary_tolerates_previous_assessment_without_matching_factors():
    from app.services.risk_engine.engine import diff_assessments
    cur = run("landslide", {"rain_24h_mm": 120})
    out = diff_assessments({"risk_tier": "LOW", "reliability": "GOOD", "factors": [], "assessed_at": "x"}, cur)
    assert out["items"] == ["Risk tier changed LOW → ELEVATED."]


@pytest.mark.parametrize("overrides,fragment", [
    ([1, 2], "JSON object"), ({"landslide": 5}, "must be an object"),
    ({"landslide": {"soil_moisture_baseline_pct": -3}}, "non-negative"),
    ({"landslide": {"soil_moisture_baseline_pct": float("nan")}}, "finite"),
])
def test_threshold_validation_messages(overrides, fragment):
    from app.services.risk_engine import validate_site_overrides
    errors = validate_site_overrides(overrides)
    assert errors and any(fragment in e for e in errors)


@pytest.mark.parametrize("seed", range(10))
def test_property_simultaneous_outages_never_assert_low(seed):
    """Invariant 11 with several sensors failing together (e.g. a shared gateway or power loss).

    Added in the second audit pass: the single-input property above does not cover combined outages.
    """
    rng = random.Random(5000 + seed)
    for _ in range(100):
        hazard = rng.choice(["landslide", "flash_flood"])
        keys = [r.key for r in RULES[hazard]]
        values = {k: rng.choice([BENIGN[k], rng.uniform(0, 150), rng.uniform(0, 8)]) for k in BENIGN}
        before = run(hazard, values)
        lost = rng.sample(keys, rng.randint(1, len(keys)))
        how = rng.choice(["missing", "stale"])
        after = run(hazard, {**values, **{k: (None if how == "missing" else values[k]) for k in lost}},
                    {k: how for k in lost})
        if before["risk_tier"] != "LOW":
            assert after["risk_tier"] != "LOW", (hazard, lost, how, values)
        if after["risk_tier"] == "LOW":
            assert after["reliability"] != "POOR"
        if after["risk_tier"] != "INSUFFICIENT_DATA" and how == "missing":
            assert TIER_ORDER[after["max_possible_tier"]] >= TIER_ORDER[before["risk_tier"]], (hazard, lost, values)
