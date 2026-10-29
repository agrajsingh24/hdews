"""API contract: methods, status codes, error shape, pagination, payload limits, unicode, error leakage."""
import pytest

from tests.conftest import login


def assert_error(r, status, code):
    assert r.status_code == status, r.text
    body = r.json()
    assert set(body) == {"error"} and body["error"]["code"] == code and body["error"]["message"]


def test_wrong_method_is_405_with_allow_header(client):
    """HDEWS-023: wrong methods returned 404 'No such endpoint' via the static-file mount."""
    r = client.get("/api/auth/login")
    assert_error(r, 405, "method_not_allowed")
    assert r.headers["allow"] == "POST"
    assert client.delete("/api/alerts/x").status_code == 405


def test_unknown_api_path_is_json_404(client):
    assert_error(client.get("/api/does/not/exist"), 404, "not_found")


def test_invalid_json_variants(client, auth):
    h = {**auth["reviewer"], "content-type": "application/json"}
    assert_error(client.post("/api/auth/login", content=b"{bad", headers=h), 400, "invalid_json")
    assert_error(client.post("/api/auth/login", content=b"\xff\xfe", headers=h), 400, "invalid_json")
    assert_error(client.post("/api/auth/login", content=b"[1,2]", headers=h), 422, "validation_error")
    assert_error(client.post("/api/auth/login", content=b'"text"', headers=h), 422, "validation_error")
    assert_error(client.post("/api/auth/login", content=b'{"username":"a","password":NaN}', headers=h), 400, "invalid_json")


def test_body_size_limit(client):
    """HDEWS-004: bodies were fully buffered regardless of size."""
    big = b'{"username":"' + b"a" * 1_100_000 + b'","password":"x"}'
    assert_error(client.post("/api/auth/login", content=big, headers={"content-type": "application/json"}), 413, "payload_too_large")


def test_validation_errors_list_fields_without_echoing_values(client, auth):
    secret = "s3cr3t-value-should-not-echo"
    r = client.post("/api/alerts/x/actions", headers=auth["reviewer"], json={"action_type": secret, "notes": "ok ok"})
    assert_error(r, 422, "validation_error")
    assert secret not in r.text
    assert r.json()["error"]["details"][0]["field"] == "action_type"


@pytest.mark.parametrize("q", ["limit=0", "limit=201", "offset=-1", "limit=abc", "offset=1.5"])
def test_pagination_bounds(client, auth, q):
    assert_error(client.get(f"/api/assessments?{q}", headers=auth["viewer"]), 422, "validation_error")


@pytest.mark.parametrize("path", ["/api/assessments", "/api/alerts?status=all", "/api/incidents", "/api/audit-log"])
def test_paginated_list_schema_and_defaults(client, auth, path):
    body = client.get(path, headers=auth["viewer"]).json()
    assert set(body) == {"items", "total", "limit", "offset", "has_more"}
    assert body["offset"] == 0 and body["limit"] == 50
    assert body["has_more"] == (len(body["items"]) < body["total"])


def test_pagination_pages_do_not_overlap(client, auth):
    a = client.get("/api/audit-log?limit=5&offset=0", headers=auth["viewer"]).json()["items"]
    b = client.get("/api/audit-log?limit=5&offset=5", headers=auth["viewer"]).json()["items"]
    assert not {x["seq"] for x in a} & {x["seq"] for x in b}


def test_empty_results(client, auth):
    body = client.get("/api/incidents?q=zzzzzz-nothing", headers=auth["viewer"]).json()
    assert body == {"items": [], "total": 0, "limit": 50, "offset": 0, "has_more": False}
    assert client.get("/api/alerts?status=resolved", headers=auth["viewer"]).json()["total"] == 0


def test_search_wildcards_are_literal(client, auth):
    """HDEWS-020: '%' or '_' in search text acted as SQL LIKE wildcards and matched everything."""
    assert client.get("/api/incidents?q=%25", headers=auth["viewer"]).json()["total"] == 0
    assert client.get("/api/incidents?q=_", headers=auth["viewer"]).json()["total"] == 0
    assert client.get("/api/audit-log?event_prefix=%25", headers=auth["viewer"]).json()["total"] == 0


def test_unicode_round_trips(client, auth):
    alert_note = "निरीक्षण जारी — slope ✓ 測試"
    client.post("/api/demo/scenario", headers=auth["analyst"], json={"site_ids": ["SNP-05"], "preset": "rising_landslide_indicators"})
    aid = client.get("/api/alerts?site_id=SNP-05", headers=auth["viewer"]).json()["items"][0]["id"]
    client.post(f"/api/alerts/{aid}/acknowledge", headers=auth["reviewer"], json={"notes": alert_note})
    actions = client.get(f"/api/alerts/{aid}", headers=auth["viewer"]).json()["actions"]
    assert actions[0]["notes"] == alert_note
    assert client.get("/api/incidents?q=निरीक्षण", headers=auth["viewer"]).status_code == 200


def test_unexpected_exception_is_generic_500_without_internals(database, monkeypatch):
    from app.api import routes_core
    from tests.conftest import make_client

    def boom(*a, **k):
        raise RuntimeError("DATABASE PASSWORD=hunter2 at /srv/secret/path.py line 42")
    monkeypatch.setattr(routes_core, "latest_assessment", boom)
    with make_client(database, raise_server_exceptions=False) as c:
        r = c.get("/api/overview", headers=login(c, "viewer"))
    assert_error(r, 500, "internal_error")
    assert "hunter2" not in r.text and "Traceback" not in r.text and "/srv" not in r.text


def test_unknown_resources_are_404(client, auth):
    h = auth["viewer"]
    for path in ("/api/sites/NOPE", "/api/sites/NOPE/observations", "/api/assessments/as_nope",
                 "/api/assessments/as_nope/explanation", "/api/alerts/al_nope", "/api/incidents/INC-NOPE"):
        assert_error(client.get(path, headers=h), 404, "not_found")
    assert_error(client.post("/api/sites/NOPE/assess", headers=auth["analyst"]), 404, "not_found")
    assert_error(client.post("/api/demo/scenario", headers=auth["analyst"], json={"site_ids": ["NOPE"], "preset": "normal"}),
                 404, "not_found")


def test_response_schemas_for_core_endpoints(client, auth):
    h = auth["viewer"]
    o = client.get("/api/overview", headers=h).json()
    assert {"generated_at", "data_mode", "sites", "open_alerts", "sensor_states", "rain_hourly", "tier_counts"} <= set(o)
    site = client.get("/api/sites/SNP-05", headers=h).json()
    assert {"site", "sensors", "assessments", "indicators", "effective_config", "alerts", "incidents"} <= set(site)
    for a in site["assessments"].values():
        assert {"risk_tier", "reliability", "factors", "evidence_observation_ids", "rule_version", "assessed_at",
                "missing_inputs", "review_steps", "tier_is_lower_bound", "max_possible_tier", "data_origin"} <= set(a)
    obs = client.get("/api/sites/SNP-05/observations?hours=1", headers=h).json()
    for series in obs["series"]:
        assert {"id", "sensor_type", "unit", "points"} <= set(series)


@pytest.mark.parametrize("bad", [{"site_ids": []}, {"site_ids": ["AGM-03"]}, {"site_ids": ["AGM-03"], "preset": "bogus"},
                                 {"site_ids": "AGM-03", "preset": "normal"},
                                 {"site_ids": ["AGM-03"], "overrides": {"rain_mmh": 5}},
                                 {"site_ids": ["AGM-03"], "overrides": {"soil_moisture_pct": 999}}])
def test_scenario_validation(client, auth, bad):
    """Includes HDEWS-005: a misspelt parameter used to be silently ignored."""
    assert_error(client.post("/api/demo/scenario", headers=auth["analyst"], json=bad), 422, "validation_error")


@pytest.mark.parametrize("overrides", [
    {"landslide": {"rain_24h_mm": {"watch": True, "high": 2}}},
    {"landslide": {"rain_24hr_mm": {"watch": 1, "high": 2}}},
    {"landslide": {"rain_24h_mm": {"watch": 1, "high": 2, "extreme": 3}}},
    {"landslide": {"soil_moisture_baseline_pct": "28"}},
    {"tiers": {"high_min_score": 99}},
    {"flash_flood": {"river_warning_level_m": 5, "river_danger_level_m": 4}},
    {"landslide": {"rain_24h_mm": {"watch": -1, "high": 2}}},
])
def test_threshold_editor_rejects_invalid_config_and_leaves_it_unchanged(client, auth, database, overrides):
    """HDEWS-006: booleans, misspelt keys and non-finite values were accepted (or crashed after saving)."""
    with database.tx() as tx:
        before = tx.scalar("SELECT config FROM sites WHERE id = 'AGM-03'")
    r = client.put("/api/sites/AGM-03/config", headers=auth["admin"], json={"overrides": overrides})
    assert_error(r, 422, "validation_error")
    with database.tx() as tx:
        assert tx.scalar("SELECT config FROM sites WHERE id = 'AGM-03'") == before


def test_threshold_editor_rejects_infinity(client, auth, database):
    r = client.put("/api/sites/AGM-03/config", headers={**auth["admin"], "content-type": "application/json"},
                   content=b'{"overrides":{"landslide":{"rain_24h_mm":{"watch":1,"high":1e999}}}}')
    assert_error(r, 422, "validation_error")
    assert client.get("/api/sites/AGM-03", headers=auth["viewer"]).status_code == 200
