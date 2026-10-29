"""Scenario simulator and continuing telemetry."""
from datetime import timedelta

import pytest
from pydantic import ValidationError

from app import clock
from app.services import assessments, simulator
from tests.conftest import counts, ingest, now_iso

ADMIN = {"id": "u_admin", "display_name": "Demo Administrator", "role": "admin"}
EXPECTED = {  # preset -> SNP-05 (landslide, flash_flood) tiers
    "normal": ("LOW", "LOW"),
    "increasing_rainfall": ("ELEVATED", "ELEVATED"),
    "rising_landslide_indicators": ("HIGH", "ELEVATED"),
    "rapid_river_rise": ("ELEVATED", "HIGH"),
    "sensor_outage_adverse_weather": ("ELEVATED", "ELEVATED"),
}


def apply(db, preset, overrides=None, sites=("SNP-05",)):
    with db.tx() as tx:
        res = simulator.apply_scenario(tx, list(sites), preset, overrides, ADMIN)
        out = {a["hazard"]: a for s in sites for a in assessments.run_site(tx, s, "test")}
    return res, out


def sim_rows(db, site="SNP-05"):
    with db.tx() as tx:
        return tx.all("SELECT * FROM observations WHERE site_id = ? AND origin = 'SIMULATED' ORDER BY sensor_id, observed_at", (site,))


@pytest.mark.parametrize("preset", simulator.PRESETS)
def test_every_preset_produces_documented_tiers(database, preset):
    _, a = apply(database, preset)
    assert (a["landslide"]["risk_tier"], a["flash_flood"]["risk_tier"]) == EXPECTED[preset]
    assert all(x["data_origin"] == "SIMULATED" for x in a.values())


def test_generated_readings_are_ordered_aligned_labelled_and_in_range(database):
    apply(database, "rising_landslide_indicators")
    rows = sim_rows(database)
    by_sensor = {}
    for r in rows:
        by_sensor.setdefault(r["sensor_id"], []).append(r)
    now = clock.now()
    for rs in by_sensor.values():
        times = [clock.parse(r["observed_at"]) for r in rs]
        assert times == sorted(times) and len(set(times)) == len(times)
        assert all(int(t.timestamp()) % 900 == 0 for t in times)
        assert all(t <= now and clock.parse(r["received_at"]) <= now for t, r in zip(times, rs))
        assert now - times[0] <= timedelta(hours=48)
    assert all(r["origin"] == "SIMULATED" and r["source_id"] == "SIM-GATEWAY" and "Not a real measurement" in r["provenance"] for r in rows)
    assert all(r["quality_status"] == "good" and r["value"] is not None for r in rows)
    soil = [r["value"] for r in by_sensor["SNP-05-SOIL"]]
    assert abs(soil[-1] - 45) < 1


def test_repeat_is_deterministic(database, monkeypatch):
    clock.set_frozen_now(clock.parse("2026-10-28T10:07:00Z"))
    apply(database, "increasing_rainfall")
    first = [(r["sensor_id"], r["observed_at"], r["value"]) for r in sim_rows(database)]
    apply(database, "increasing_rainfall")
    second = [(r["sensor_id"], r["observed_at"], r["value"]) for r in sim_rows(database)]
    assert first == second


def test_scenario_never_touches_observed_records(client, database, auth):
    ingest(client, [{"sensor_id": "SNP-05-SOIL", "observed_at": now_iso(client), "value": 33.3, "idempotency_key": "real"}])
    client.post("/api/demo/scenario", headers=auth["analyst"], json={"site_ids": ["SNP-05"], "preset": "rapid_river_rise"})
    with database.tx() as tx:
        row = tx.one("SELECT * FROM observations WHERE idempotency_key = 'FIELD-GATEWAY-01:real'")  # namespaced per source (HDEWS-032)
    assert row["value"] == 33.3 and row["origin"] == "OBSERVED"


def test_scenario_application_is_atomic_across_sites(client, database, auth):
    before = counts(database, "observations", "scenario_runs")
    r = client.post("/api/demo/scenario", headers=auth["analyst"], json={"site_ids": ["SNP-05", "NOPE"], "preset": "normal"})
    assert r.status_code == 404
    assert counts(database, "observations", "scenario_runs") == before


def test_duplicate_site_ids_are_applied_once(client, auth, database):
    before = counts(database, "scenario_runs")["scenario_runs"]
    r = client.post("/api/demo/scenario", headers=auth["analyst"], json={"site_ids": ["SNP-05", "SNP-05"], "preset": "normal"}).json()
    assert len(r["assessments"]) == 2 and counts(database, "scenario_runs")["scenario_runs"] == before + 1


def test_tick_continues_telemetry_without_duplicates_and_keeps_outage(database):
    apply(database, "sensor_outage_adverse_weather")
    n0 = len(sim_rows(database))
    start = clock.now()
    for minutes in (0, 20, 40, 101, 162):
        clock.set_frozen_now(start + timedelta(minutes=minutes))
        with database.tx() as tx:
            simulator.tick(tx)
    rows = sim_rows(database)
    keys = [(r["sensor_id"], r["observed_at"]) for r in rows]
    assert len(keys) == len(set(keys)), "tick must not duplicate readings"
    assert len(rows) > n0
    soil = [r for r in rows if r["sensor_id"] == "SNP-05-SOIL"]
    assert clock.parse(soil[-1]["observed_at"]) < clock.now() - timedelta(hours=6), "offline sensor must stay offline"


def test_tick_is_idempotent_at_same_instant(database):
    apply(database, "normal")
    clock.set_frozen_now(clock.now() + timedelta(minutes=30))
    with database.tx() as tx:
        first = simulator.tick(tx)
    with database.tx() as tx:
        second = simulator.tick(tx)
    assert first > 0 and second == 0


def test_long_running_tick_bounded_growth(database):
    """Six simulated hours of 1-minute ticks: exactly one reading per sensor per interval."""
    apply(database, "normal", sites=("TLW-02",))
    start = clock.now()
    with database.tx() as tx:
        base = tx.scalar("SELECT COUNT(*) FROM observations WHERE site_id = 'TLW-02'")
    for m in range(1, 361):  # noqa: B007
        clock.set_frozen_now(start + timedelta(minutes=m))
        with database.tx() as tx:
            simulator.tick(tx)
    with database.tx() as tx:
        n = tx.scalar("SELECT COUNT(*) FROM observations WHERE site_id = 'TLW-02'")
    assert 46 <= n - base <= 50  # 2 sensors x 6 h x 4/h = 48 (+/- grid alignment)


def test_recovery_only_after_valid_observations_arrive(client, database, auth):
    """Scenario D: during an outage, the site recovers only when real readings for the offline sensors arrive."""
    # Pin the clock: the delayed extensometer's age otherwise depends on where "now" falls in the 15-min grid.
    clock.set_frozen_now(clock.parse("2026-10-28T10:00:00Z"))
    client.post("/api/demo/scenario", headers=auth["analyst"], json={"site_ids": ["SNP-05"], "preset": "sensor_outage_adverse_weather"})
    a = {x["hazard"]: x for x in client.post("/api/sites/SNP-05/assess", headers=auth["analyst"]).json()["assessments"]}
    assert a["landslide"]["reliability"] == "POOR"
    # A tick does not restore offline sensors.
    clock.set_frozen_now(clock.now() + timedelta(minutes=16))
    with database.tx() as tx:
        simulator.tick(tx)
    a = {x["hazard"]: x for x in client.post("/api/sites/SNP-05/assess", headers=auth["analyst"]).json()["assessments"]}
    assert a["landslide"]["reliability"] == "POOR"
    # Valid readings arrive for the offline sensors (observed, through the gateway).
    now = clock.now()
    readings = []
    for i in range(6):
        t = clock.iso(now - timedelta(minutes=15 * i))
        readings += [{"sensor_id": "SNP-05-SOIL", "observed_at": t, "value": 30.0},
                     {"sensor_id": "SNP-05-RIVER", "observed_at": t, "value": 1.2}]
    ingest(client, readings)
    a = {x["hazard"]: x for x in client.post("/api/sites/SNP-05/assess", headers=auth["analyst"]).json()["assessments"]}
    assert a["flash_flood"]["reliability"] != "POOR"
    soil = next(f for f in a["landslide"]["factors"] if f["key"] == "soil_moisture_pct")
    assert soil["status"] == "available" and soil["origins"] == ["OBSERVED"]
    # The extensometer link is still delayed, so its data is stale: slope movement is decisive during heavy
    # rain, so the landslide assessment must stay POOR until displacement data arrives as well.
    assert a["landslide"]["reliability"] == "POOR"
    assert [m["key"] for m in a["landslide"]["missing_inputs"]] == ["displacement_24h_mm"]
    ext = [{"sensor_id": "SNP-05-EXT", "observed_at": clock.iso(now - timedelta(minutes=15 * i)), "value": 14.0}
           for i in range(3)] + [{"sensor_id": "SNP-05-EXT", "observed_at": clock.iso(now - timedelta(hours=24)), "value": 13.0}]
    ingest(client, ext)
    a = {x["hazard"]: x for x in client.post("/api/sites/SNP-05/assess", headers=auth["analyst"]).json()["assessments"]}
    assert a["landslide"]["reliability"] != "POOR" and not a["landslide"]["missing_inputs"]
    assert {x["data_origin"] for x in a.values()} == {"MIXED"}


@pytest.mark.parametrize("overrides", [{"rain_mm_h": 151}, {"soil_moisture_pct": -1}, {"offline_sensors": ["camera"]},
                                       {"outage_minutes": 99999}, {"bogus": 1}])
def test_invalid_custom_inputs_rejected(database, overrides):
    with pytest.raises(ValidationError):
        apply(database, None, overrides)
