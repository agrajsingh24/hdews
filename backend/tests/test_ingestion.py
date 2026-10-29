"""Sensor ingestion: authentication, validation, units, scope, idempotency, limits, atomicity, concurrency."""
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest

from app import clock
from tests.conftest import INGEST_KEY, counts, ingest, now_iso

URL = "/api/ingestion/FIELD-GATEWAY-01"
KEY = {"X-HDEWS-Ingest-Key": INGEST_KEY}


def reading(client, **over):
    return {"sensor_id": "AGM-03-SOIL", "observed_at": now_iso(client), "value": 31.5, **over}


def stored(database, sensor="AGM-03-SOIL", origin="OBSERVED"):
    with database.tx() as tx:
        return tx.all("SELECT * FROM observations WHERE sensor_id = ? AND origin = ? ORDER BY observed_at", (sensor, origin))


def test_valid_reading_is_stored_with_provenance_and_both_timestamps(client, database):
    t = clock.iso(clock.now() - timedelta(minutes=10))
    r = ingest(client, [reading(client, observed_at=t, idempotency_key="k1")])
    assert r.status_code == 202 and r.json()["accepted"] == 1
    row = stored(database)[-1]
    assert row["observed_at"] == t and row["received_at"] >= t
    assert row["source_id"] == "FIELD-GATEWAY-01" and "FIELD-GATEWAY-01" in row["provenance"]
    assert row["unit"] == "% VWC" and row["quality_status"] == "good" and row["origin"] == "OBSERVED"


@pytest.mark.parametrize("key", [None, "", "wrong", INGEST_KEY + "x", INGEST_KEY.upper()])
def test_bad_ingestion_keys(client, database, key):
    before = counts(database, "observations")
    headers = {"X-HDEWS-Ingest-Key": key} if key is not None else {}
    r = client.post(URL, json={"readings": [reading(client)]}, headers=headers)
    assert r.status_code == 401 and r.json()["error"]["code"] == "ingest_unauthorized"
    assert counts(database, "observations") == before


def test_unknown_and_non_push_sources(client):
    assert ingest(client, [reading(client)], source="NOPE").status_code == 404
    assert ingest(client, [reading(client)], source="SIM-GATEWAY").status_code == 404
    assert ingest(client, [reading(client)], source="NASA-GPM-IMERG").status_code == 404


def test_disabled_source_is_refused(client, database):
    with database.tx() as tx:
        tx.execute("UPDATE data_sources SET enabled = 0 WHERE id = 'FIELD-GATEWAY-01'")
    assert ingest(client, [reading(client)]).status_code == 401


@pytest.mark.parametrize("raw", [
    '{"readings":[{"sensor_id":"AGM-03-SOIL","observed_at":"%s","value":Infinity}]}',
    '{"readings":[{"sensor_id":"AGM-03-SOIL","observed_at":"%s","value":-Infinity}]}',
    '{"readings":[{"sensor_id":"AGM-03-SOIL","observed_at":"%s","value":NaN}]}',
])
def test_nan_and_infinity_literals_rejected(client, database, raw):
    """HDEWS-001: an Infinity reading was accepted and then crashed /api/overview with a 500."""
    before = counts(database, "observations")
    r = client.post(URL, content=(raw % now_iso(client)).encode(), headers={**KEY, "content-type": "application/json"})
    assert r.status_code == 400
    assert counts(database, "observations") == before


def test_overflowing_number_rejected(client):
    raw = '{"readings":[{"sensor_id":"AGM-03-SOIL","observed_at":"%s","value":1e999}]}' % now_iso(client)
    r = client.post(URL, content=raw.encode(), headers={**KEY, "content-type": "application/json"})
    assert r.status_code == 422


def test_previously_stored_infinity_cannot_crash_views(lenient_client, database, auth):
    """Defence in depth for HDEWS-001: rows written before the fix must not take the dashboard down."""
    with database.tx() as tx:
        tx.execute("INSERT INTO observations (sensor_id, site_id, source_id, metric, value, unit, observed_at, received_at, "
                   "quality_status, origin, provenance) VALUES ('AGM-03-SOIL','AGM-03','FIELD-GATEWAY-01','soil_moisture_vwc_pct',"
                   "?, '% VWC', ?, ?, 'bad', 'OBSERVED', 'legacy row')", (float("inf"), clock.now_iso(), clock.now_iso()))
    h = auth["viewer"]
    assert lenient_client.get("/api/overview", headers=h).status_code == 200
    body = lenient_client.get("/api/sites/AGM-03/observations?hours=1", headers=h)
    assert body.status_code == 200
    soil = next(s for s in body.json()["series"] if s["id"] == "AGM-03-SOIL")
    assert any(p["v"] is None and p["q"] == "bad" for p in soil["points"])


@pytest.mark.parametrize("unit,ok", [("% VWC", True), (" % VWC ", True), ("%", False), ("in", False)])
def test_unit_must_match_sensor_registry(client, unit, ok):
    """HDEWS-002: a 'unit' field was silently ignored, so feet could be stored as metres."""
    r = ingest(client, [reading(client, unit=unit)]).json()
    assert r["accepted"] == (1 if ok else 0)
    if not ok:
        assert "does not match the registered unit" in r["rejected"][0]["error"]


def test_unknown_fields_rejected(client):
    r = ingest(client, [reading(client, temprature=3)])
    assert r.status_code == 422
    assert client.post(URL, json={"readings": [reading(client)], "extra": 1}, headers=KEY).status_code == 422


@pytest.mark.parametrize("missing", ["sensor_id", "observed_at", "value"])
def test_missing_required_fields(client, missing):
    r = reading(client)
    r.pop(missing)
    assert ingest(client, [r]).status_code == 422


@pytest.mark.parametrize("value", ["12.5", "abc", [], {}])
def test_wrong_value_types(client, value):
    r = ingest(client, [reading(client, value=value)])
    if value == "12.5":  # numeric strings are coerced by Pydantic's lax mode — documented behaviour
        assert r.status_code == 202
    else:
        assert r.status_code == 422


@pytest.mark.parametrize("sensor,value,quality", [
    ("AGM-03-SOIL", -0.1, "bad"), ("AGM-03-SOIL", 100.1, "bad"), ("AGM-03-SOIL", 0.0, "good"), ("AGM-03-SOIL", 100.0, "good"),
    ("AGM-03-RAIN", -1, "bad"), ("AGM-03-RAIN", 120.0, "good"), ("AGM-03-RIVER", 51, "bad"), ("AGM-03-EXT", -50, "good"),
])
def test_physical_range_checks_mark_bad_but_keep_extreme_plausible_values(client, database, sensor, value, quality):
    """Implausible values are kept for traceability but flagged 'bad' (excluded from assessment).
    120 mm in one 15-min interval is extreme but within the documented gauge range, so it stays 'good'."""
    ingest(client, [reading(client, sensor_id=sensor, value=value)])
    assert stored(database, sensor)[-1]["quality_status"] == quality


def test_null_value_is_stored_as_missing(client, database):
    ingest(client, [reading(client, value=None)])
    assert stored(database)[-1]["quality_status"] == "missing"


def test_future_and_naive_timestamps_rejected_old_ones_accepted(client):
    future = clock.iso(clock.now() + timedelta(minutes=10))
    assert ingest(client, [reading(client, observed_at=future)]).status_code == 422
    assert ingest(client, [reading(client, observed_at="2026-07-15T10:00:00")]).status_code == 422  # no timezone
    assert ingest(client, [reading(client, observed_at="yesterday")]).status_code == 422
    assert ingest(client, [reading(client, observed_at="2019-01-01T00:00:00Z")]).json()["accepted"] == 1


def test_offset_timestamps_are_normalised_to_utc(client, database):
    ist = (clock.now() - timedelta(minutes=5)).astimezone(clock.parse("2026-01-01T00:00:00+05:30").tzinfo)
    ingest(client, [reading(client, observed_at=ist.isoformat())])
    assert stored(database)[-1]["observed_at"] == clock.iso(ist)


def test_very_old_reading_does_not_make_a_sensor_look_fresh(client, auth):
    ingest(client, [reading(client, sensor_id="SNP-05-SOIL", observed_at="2019-01-01T00:00:00Z")])
    site = client.get("/api/sites/SNP-05", headers=auth["viewer"]).json()
    soil = next(s for s in site["sensors"] if s["id"] == "SNP-05-SOIL")
    assert soil["health"]["last_observed_at"] != "2019-01-01T00:00:00Z"


def test_idempotency_and_duplicates(client, database):
    r1 = ingest(client, [reading(client, idempotency_key="dev-1")]).json()
    r2 = ingest(client, [reading(client, idempotency_key="dev-1", value=99)]).json()
    assert (r1["accepted"], r2["accepted"], r2["duplicates"]) == (1, 0, 1)
    t = now_iso(client)
    ingest(client, [reading(client, observed_at=t)])
    again = ingest(client, [reading(client, observed_at=t)]).json()
    assert again["duplicates"] == 1
    assert len([o for o in stored(database) if o["observed_at"] == t]) == 1


def test_reordered_readings_are_stored_and_assessed_in_time_order(client, database):
    base = clock.now() - timedelta(minutes=50)
    batch = [reading(client, observed_at=clock.iso(base + timedelta(minutes=m)), value=30 + m / 10) for m in (40, 0, 20)]
    assert ingest(client, batch).json()["accepted"] == 3
    times = [o["observed_at"] for o in stored(database)]
    assert times == sorted(times)


def test_batch_limits(client):
    assert ingest(client, []).status_code == 422
    many = [reading(client, idempotency_key=f"k{i}") for i in range(501)]
    assert ingest(client, many).status_code == 422
    huge = b'{"readings":[' + b",".join([b'{"sensor_id":"x","observed_at":"2026-01-01T00:00:00Z","value":1}'] * 20000) + b"]}"
    r = client.post(URL, content=huge, headers={**KEY, "content-type": "application/json"})
    assert r.status_code == 413


def test_source_site_scope_is_enforced(client, database):
    """HDEWS-007: any gateway key could write readings for every site."""
    with database.tx() as tx:
        tx.execute("UPDATE data_sources SET ingest_site_scope = ? WHERE id = 'FIELD-GATEWAY-01'", (json.dumps(["AGM-03"]),))
    r = ingest(client, [reading(client), reading(client, sensor_id="SNP-05-SOIL")]).json()
    assert r["accepted"] == 1 and r["rejected"][0]["sensor_id"] == "SNP-05-SOIL"
    with database.tx() as tx:
        tx.execute("UPDATE data_sources SET ingest_site_scope = NULL WHERE id = 'FIELD-GATEWAY-01'")
    assert ingest(client, [reading(client, value=40)]).json()["accepted"] == 0


def test_ingestion_rate_limit(client):
    codes = [ingest(client, [reading(client, idempotency_key=f"r{i}")]).status_code for i in range(122)]
    assert codes.count(429) == 2 and 429 not in codes[:120]


def test_database_failure_mid_batch_rolls_back_everything(database, monkeypatch):
    from app.services import ingestion
    from tests.conftest import make_client
    real_insert = ingestion.Tx.insert
    calls = {"n": 0}

    def flaky(self, table, values, returning=None):
        if table == "observations":
            calls["n"] += 1
            if calls["n"] == 2:
                raise RuntimeError("disk I/O error")
        return real_insert(self, table, values, returning)
    monkeypatch.setattr(ingestion.Tx, "insert", flaky)
    before = counts(database, "observations", "audit_log")
    with make_client(database, raise_server_exceptions=False) as c:
        r = ingest(c, [reading(c, idempotency_key="a"), reading(c, idempotency_key="b", observed_at=clock.iso(clock.now() - timedelta(minutes=1)))])
    assert r.status_code == 500 and "disk" not in r.text
    assert counts(database, "observations", "audit_log") == before, "no partial batch may be committed"


def test_concurrent_submissions_of_the_same_reading_store_it_once(client, database):
    body = {"readings": [reading(client, idempotency_key="same-key")]}
    with ThreadPoolExecutor(8) as pool:
        results = list(pool.map(lambda _: client.post(URL, json=body, headers=KEY).json(), range(8)))
    assert sum(r["accepted"] for r in results) == 1
    with database.tx() as tx:
        assert tx.scalar("SELECT COUNT(*) FROM observations WHERE idempotency_key = 'FIELD-GATEWAY-01:same-key'") == 1  # keys are namespaced per source (HDEWS-032)


def test_ingested_reading_triggers_reassessment_with_mixed_origin(client, auth):
    ingest(client, [reading(client)])
    a = client.get("/api/assessments?site_id=AGM-03&hazard=landslide&limit=1", headers=auth["viewer"]).json()["items"][0]
    assert a["trigger"] == "ingestion:FIELD-GATEWAY-01" and a["data_origin"] == "MIXED"


def test_observed_rain_does_not_double_count_with_simulated(client, auth):
    """HDEWS-003 end to end: re-sending the simulated rain series as observed must not change the 1 h total."""
    v = auth["viewer"]
    before = client.get("/api/sites/SNP-05", headers=v).json()["indicators"]["rain_1h_mm"]["value"]
    pts = next(s for s in client.get("/api/sites/SNP-05/observations?hours=2", headers=v).json()["series"]
               if s["sensor_type"] == "rain_gauge")["points"]
    ingest(client, [{"sensor_id": "SNP-05-RAIN", "observed_at": p["t"], "value": p["v"]} for p in pts])
    after = client.get("/api/sites/SNP-05", headers=v).json()["indicators"]["rain_1h_mm"]
    assert after["value"] == before and after["origins"] == ["OBSERVED"]


@pytest.mark.parametrize("quality,expected", [("suspect", "suspect"), ("bad", "bad"), ("good", "good")])
def test_gateway_quality_flags_are_kept(client, database, quality, expected):
    ingest(client, [reading(client, quality_status=quality)])
    assert stored(database)[-1]["quality_status"] == expected


def test_unknown_quality_flag_rejected(client):
    assert ingest(client, [reading(client, quality_status="excellent")]).status_code == 422
