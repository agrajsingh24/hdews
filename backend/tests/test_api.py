"""API integration tests: auth, RBAC, data endpoints, validation, pagination."""
from tests.conftest import INGEST_KEY, make_client


def test_health_and_meta_are_public(client):
    assert client.get("/api/health").json()["status"] == "ok"
    meta = client.get("/api/meta").json()
    assert "not a certified" in meta["safety_notice"].lower()
    assert meta["threshold_status"].startswith("EXPERIMENTAL")


def test_login_logout_and_me(client):
    bad = client.post("/api/auth/login", json={"username": "reviewer", "password": "wrong"})
    assert bad.status_code == 401 and bad.json()["error"]["code"] == "invalid_credentials"
    from tests.conftest import login
    h = login(client, "reviewer")
    me = client.get("/api/auth/me", headers=h).json()
    assert me["user"]["role"] == "reviewer" and "alert_review" in me["permissions"]
    client.post("/api/auth/logout", headers=h)
    assert client.get("/api/auth/me", headers=h).status_code == 401


def test_protected_endpoints_require_auth(client):
    for path in ("/api/overview", "/api/sites", "/api/alerts", "/api/audit-log", "/api/evaluation"):
        r = client.get(path)
        assert r.status_code == 401, path
        assert r.json()["error"]["code"] == "unauthenticated"


def test_validation_errors_are_structured(client, auth):
    r = client.post("/api/auth/login", json={"username": ""})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "validation_error"
    assert client.get("/api/alerts?limit=0", headers=auth["viewer"]).status_code == 422
    assert client.get("/api/alerts?status=bogus", headers=auth["viewer"]).status_code == 422
    r = client.post("/api/demo/scenario", headers=auth["analyst"],
                    json={"site_ids": ["AGM-03"], "overrides": {"rain_mm_h": -5}})
    assert r.status_code == 422
    assert any("rain_mm_h" in d["field"] for d in r.json()["error"]["details"])
    r = client.post("/api/demo/scenario", headers=auth["analyst"],
                    json={"site_ids": ["AGM-03"], "overrides": {"offline_sensors": ["laser"]}})
    assert r.status_code == 422
    assert client.post("/api/auth/login", content=b"{not json", headers={"content-type": "application/json"}).status_code == 400


def test_unknown_api_route_returns_json_404(client):
    r = client.get("/api/nope")
    assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"


def test_overview_reports_simulated_data_mode(client, auth):
    o = client.get("/api/overview", headers=auth["viewer"]).json()
    assert o["data_mode"] == "SIMULATED"
    assert len(o["sites"]) == 6
    assert o["sensor_total"] == 19
    assert o["sensor_states"].get("MAINTENANCE") == 1
    assert len(o["rain_hourly"]["hours"]) == 24
    assert o["tier_counts"]


def test_site_detail_readings_have_value_unit_time_quality_source(client, auth):
    d = client.get("/api/sites/SNP-05", headers=auth["viewer"]).json()
    assert {s["sensor_type"] for s in d["sensors"]} == {"rain_gauge", "soil_moisture", "extensometer", "river_stage"}
    for s in d["sensors"]:
        assert s["unit"] and s["health"]["last_observed_at"] and s["source"]["origin"] == "SIMULATED"
    obs = client.get("/api/sites/SNP-05/observations?hours=6", headers=auth["viewer"]).json()
    p = obs["series"][0]["points"][-1]
    assert {"v", "t", "r", "q", "o", "src"} <= set(p)
    assert p["o"] == "SIMULATED"
    assert client.get("/api/sites/NOPE", headers=auth["viewer"]).status_code == 404
    assert client.get("/api/sites/SNP-05/observations?hours=999", headers=auth["viewer"]).status_code == 422


def test_rbac_roles(client, auth):
    alert_post = lambda h: client.post("/api/alerts/al_missing/acknowledge", headers=h, json={})
    assert alert_post(auth["viewer"]).status_code == 403
    assert alert_post(auth["analyst"]).status_code == 403
    assert alert_post(auth["reviewer"]).status_code == 404  # permitted, alert just doesn't exist
    scen = lambda h: client.post("/api/demo/scenario", headers=h, json={"site_ids": ["AGM-03"], "preset": "normal"})
    assert scen(auth["viewer"]).status_code == 403
    assert scen(auth["reviewer"]).status_code == 403
    assert scen(auth["analyst"]).status_code == 200
    cfg = lambda h: client.put("/api/sites/AGM-03/config", headers=h, json={"overrides": {}})
    assert cfg(auth["analyst"]).status_code == 403
    assert cfg(auth["admin"]).status_code == 200
    forbidden = alert_post(auth["viewer"]).json()["error"]
    assert forbidden["code"] == "forbidden" and "reviewer" in forbidden["details"]["required_roles"]


def test_site_config_validation_and_audit(client, auth):
    bad = client.put("/api/sites/AGM-03/config", headers=auth["admin"],
                     json={"overrides": {"landslide": {"rain_24h_mm": {"watch": 200, "high": 100}}}})
    assert bad.status_code == 422
    good = client.put("/api/sites/AGM-03/config", headers=auth["admin"],
                      json={"overrides": {"landslide": {"rain_24h_mm": {"watch": 40, "high": 90}}}})
    assert good.status_code == 200
    assert good.json()["effective_config"]["landslide"]["rain_24h_mm"]["watch"] == 40
    log = client.get("/api/audit-log?event_type=site.config_changed", headers=auth["viewer"]).json()
    assert log["total"] == 1 and log["items"][0]["actor_role"] == "admin"


def test_demo_endpoints_disabled_in_production(database):
    with make_client(database, app_env="production") as c:
        from tests.conftest import login
        h = login(c, "analyst")
        assert c.post("/api/demo/scenario", headers=h, json={"site_ids": ["AGM-03"], "preset": "normal"}).status_code == 404
        assert c.get("/api/demo/presets", headers=h).status_code == 404
        assert c.get("/api/meta").json()["demo_login_hint"] is None


def test_evaluation_page_reports_not_evaluated(client, auth):
    e = client.get("/api/evaluation", headers=auth["viewer"]).json()
    assert e["status"] == "NOT_EVALUATED"
    assert e["runs"] == []
    assert "Not evaluated yet" in e["message"]


def test_incidents_search_filter_and_detail(client, auth):
    h = auth["viewer"]
    all_ = client.get("/api/incidents", headers=h).json()
    assert all_["total"] == 9
    imported = client.get("/api/incidents?origin=IMPORTED", headers=h).json()
    assert imported["total"] == 3 and all(i["source_url"] for i in imported["items"])
    syn = client.get("/api/incidents?origin=SYNTHETIC", headers=h).json()
    assert all(i["title"].startswith("[SYNTHETIC]") for i in syn["items"])
    q = client.get("/api/incidents?q=gaurikund", headers=h).json()
    assert q["total"] >= 1
    d = client.get("/api/incidents/INC-REF-2023-GKD", headers=h).json()
    assert d["nearby_sites"][0]["id"] == "SNP-05"
    assert d["associated_observations"] == [] and d["associated_observations_note"]
    paged = client.get("/api/incidents?limit=2&offset=2", headers=h).json()
    assert len(paged["items"]) == 2 and paged["has_more"]


def test_data_sources_registry(client, auth):
    items = {s["id"]: s for s in client.get("/api/data-sources", headers=auth["viewer"]).json()["items"]}
    assert items["SIM-GATEWAY"]["health_status"] == "HEALTHY"
    assert items["NASA-GPM-IMERG"]["health_status"] == "NOT_CONFIGURED"
    assert "ingest_key_hash" not in items["FIELD-GATEWAY-01"]


def test_map_layers(client, auth):
    m = client.get("/api/map/layers", headers=auth["viewer"]).json()
    assert m["pilot_area"]["simulated_boundary"] is True
    assert len(m["layers"]["sites"]["items"]) == 6
    assert all(z["simulated"] for z in m["layers"]["hazard_zones"]["items"])


def test_ingestion_path(client, auth):
    reading = {"sensor_id": "AGM-03-SOIL", "observed_at": client.get("/api/health").json()["time"], "value": 31.5,
               "idempotency_key": "dev-1-0001"}
    url = "/api/ingestion/FIELD-GATEWAY-01"
    assert client.post(url, json={"readings": [reading]}).status_code == 401
    assert client.post(url, json={"readings": [reading]}, headers={"X-HDEWS-Ingest-Key": "wrong"}).status_code == 401
    assert client.post("/api/ingestion/SIM-GATEWAY", json={"readings": [reading]},
                       headers={"X-HDEWS-Ingest-Key": INGEST_KEY}).status_code == 404
    h = {"X-HDEWS-Ingest-Key": INGEST_KEY}
    r = client.post(url, json={"readings": [reading, {**reading, "sensor_id": "NOPE", "idempotency_key": "x"}]}, headers=h)
    assert r.status_code == 202
    body = r.json()
    assert body["accepted"] == 1 and len(body["rejected"]) == 1
    dup = client.post(url, json={"readings": [reading]}, headers=h).json()
    assert dup["duplicates"] == 1 and dup["accepted"] == 0
    out_of_range = {**reading, "value": 250, "idempotency_key": "dev-1-0002", "observed_at": "2020-01-01T00:00:00Z"}
    client.post(url, json={"readings": [out_of_range]}, headers=h)
    future = {**reading, "observed_at": "2099-01-01T00:00:00Z", "idempotency_key": "f"}
    assert client.post(url, json={"readings": [future]}, headers=h).status_code == 422
    obs = client.get("/api/sites/AGM-03/observations?hours=2", headers=auth["viewer"]).json()
    soil = next(s for s in obs["series"] if s["id"] == "AGM-03-SOIL")
    observed = [p for p in soil["points"] if p["o"] == "OBSERVED"]
    assert observed and observed[-1]["src"] == "FIELD-GATEWAY-01"
    latest = client.get("/api/assessments?site_id=AGM-03&hazard=landslide&limit=1", headers=auth["viewer"]).json()
    assert latest["items"][0]["data_origin"] == "MIXED"
