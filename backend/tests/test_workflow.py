"""End-to-end workflow: scenario → assessment → candidate alert → review → audit.
Also stale-data behaviour, deduplication, the append-only audit log and explanations."""
from datetime import timedelta

import pytest

from app import clock
from app.config import load_settings
from app.main import background_cycle
from app.services import audit, explanations


def apply(client, h, preset, sites=("SNP-05",), overrides=None):
    r = client.post("/api/demo/scenario", headers=h, json={"site_ids": list(sites), "preset": preset, "overrides": overrides})
    assert r.status_code == 200, r.text
    return r.json()


def open_alerts(client, h, **filters):
    q = "&".join(f"{k}={v}" for k, v in filters.items())
    return client.get(f"/api/alerts?status=open&{q}", headers=h).json()["items"]


def test_full_review_workflow(client, auth):
    analyst, reviewer, viewer = auth["analyst"], auth["reviewer"], auth["viewer"]
    assert open_alerts(client, viewer) == []

    # 1. Simulated scenario drives the backend assessment to HIGH.
    res = apply(client, analyst, "rising_landslide_indicators")
    ls = next(a for a in res["assessments"] if a["hazard"] == "landslide")
    assert ls["risk_tier"] == "HIGH" and ls["data_origin"] == "SIMULATED"

    # 2. A candidate alert exists, linked to evidence.
    alerts = open_alerts(client, viewer, site_id="SNP-05")
    assert len(alerts) == 1
    alert = alerts[0]
    assert alert["status"] == "REVIEW_REQUIRED" and alert["kind"] == "HAZARD" and alert["data_origin"] == "SIMULATED"
    detail = client.get(f"/api/alerts/{alert['id']}", headers=viewer).json()
    assert detail["evidence_observations"], "alert must reference observations"
    assert all(o["origin"] == "SIMULATED" for o in detail["evidence_observations"])
    assert detail["triggering_assessment"]["review_steps"]
    assert "Not an official warning" in detail["notice"]

    # 3. Re-applying the same condition deduplicates instead of creating a new alert.
    apply(client, analyst, "rising_landslide_indicators")
    client.post("/api/sites/SNP-05/assess", headers=analyst)
    alerts = open_alerts(client, viewer, site_id="SNP-05")
    assert len(alerts) == 1 and alerts[0]["trigger_count"] >= 3

    aid = alert["id"]
    url = f"/api/alerts/{aid}"
    # 4. Invalid transitions are rejected.
    assert client.post(f"{url}/resolve", headers=reviewer, json={"category": "false_alarm", "reason": "checked"}).status_code == 409
    assert client.post(f"{url}/actions", headers=reviewer,
                       json={"action_type": "field_verification", "notes": "Go check", "assignee": "Team A"}).status_code == 409

    # 5. Acknowledge, act, resolve.
    r = client.post(f"{url}/acknowledge", headers=reviewer, json={"notes": "Reviewing evidence"})
    assert r.status_code == 200 and r.json()["alert"]["status"] == "ACKNOWLEDGED"
    assert client.post(f"{url}/acknowledge", headers=reviewer, json={}).status_code == 409
    no_assignee = client.post(f"{url}/actions", headers=reviewer, json={"action_type": "escalation", "notes": "duty officer"})
    assert no_assignee.status_code == 409
    r = client.post(f"{url}/actions", headers=reviewer,
                    json={"action_type": "field_verification", "notes": "Inspect slope", "assignee": "Field team 2"})
    assert r.json()["alert"]["status"] == "ACTION_ASSIGNED"
    r = client.post(f"{url}/actions", headers=reviewer,
                    json={"action_type": "test_notification", "notes": "Drill message", "assignee": "Duty officer"})
    assert r.status_code == 200
    assert client.post(f"{url}/resolve", headers=reviewer, json={"category": "exercise", "reason": "x"}).status_code == 422
    r = client.post(f"{url}/resolve", headers=reviewer,
                    json={"category": "exercise", "reason": "Simulated scenario; demo exercise complete."})
    assert r.json()["alert"]["status"] == "RESOLVED"
    assert client.post(f"{url}/actions", headers=reviewer, json={"action_type": "note", "notes": "late"}).status_code == 409

    # 6. Full history is available.
    d = client.get(url, headers=viewer).json()
    events = [h["event_type"] for h in d["history"]]
    assert events[0] == "alert.created"
    assert {"alert.acknowledged", "alert.action.field_verification", "alert.action.test_notification",
            "alert.resolved"} <= set(events)
    test_note = next(a for a in d["actions"] if a["action_type"] == "test_notification")
    assert "nothing was sent" in test_note["notes"]
    assert d["alert"]["resolved_by_name"] == "Demo Duty Reviewer"
    verify = client.get("/api/audit-log/verify", headers=viewer).json()
    assert verify["valid"] and verify["events_checked"] > 10

    # 7. After resolution, a persisting condition opens a new candidate alert (not silently suppressed).
    client.post("/api/sites/SNP-05/assess", headers=analyst)
    assert len(open_alerts(client, viewer, site_id="SNP-05", hazard="landslide")) == 1


def test_sensor_outage_produces_reliability_warnings_and_data_quality_alert(client, auth):
    res = apply(client, auth["analyst"], "sensor_outage_adverse_weather")
    for a in res["assessments"]:
        assert a["reliability"] == "POOR"
        assert a["risk_tier"] != "LOW"
    kinds = {(a["hazard"], a["kind"]) for a in open_alerts(client, auth["viewer"], site_id="SNP-05")}
    assert ("landslide", "DATA_QUALITY") in kinds and ("flash_flood", "DATA_QUALITY") in kinds
    site = client.get("/api/sites/SNP-05", headers=auth["viewer"]).json()
    states = {s["sensor_type"]: s["health"]["state"] for s in site["sensors"]}
    assert states["soil_moisture"] == "OFFLINE" and states["river_stage"] == "OFFLINE"
    ext = next(s for s in site["sensors"] if s["sensor_type"] == "extensometer")
    assert ext["health"]["delayed"] is True


def test_stale_data_over_time_never_shows_low(client, auth, database):
    apply(client, auth["analyst"], "normal")
    clock.set_frozen_now(clock.now() + timedelta(hours=2))  # no new telemetry for 2 h
    r = client.post("/api/sites/SNP-05/assess", headers=auth["analyst"]).json()
    for a in r["assessments"]:
        assert a["risk_tier"] == "INSUFFICIENT_DATA"
        assert a["reliability"] == "POOR"
    # The simulated gateway catches up and the site recovers.
    background_cycle(database, load_settings(app_env="test"), {})
    r = client.post("/api/sites/SNP-05/assess", headers=auth["analyst"]).json()
    assert all(a["risk_tier"] == "LOW" and a["reliability"] == "GOOD" for a in r["assessments"])


def test_audit_log_is_append_only(database):
    with database.tx() as tx:
        with pytest.raises(Exception):
            tx.execute("UPDATE audit_log SET actor_name = 'mallory'")
    with database.tx() as tx:
        with pytest.raises(Exception):
            tx.execute("DELETE FROM audit_log")
    with database.tx() as tx:
        assert audit.verify_chain(tx)["valid"]


def test_explanation_endpoint_uses_template_without_llm(client, auth):
    a = client.get("/api/assessments?site_id=SNP-05&limit=1", headers=auth["viewer"]).json()["items"][0]
    e = client.get(f"/api/assessments/{a['id']}/explanation", headers=auth["viewer"]).json()
    assert e["method"] == "template"
    assert "SIMULATED" in e["text"]
    assert "Not an official warning" in e["disclaimer"]


def test_llm_output_is_rejected_when_it_invents_numbers(client, auth):
    a_id = client.get("/api/assessments?site_id=SNP-05&limit=1", headers=auth["viewer"]).json()["items"][0]["id"]
    a = client.get(f"/api/assessments/{a_id}", headers=auth["viewer"]).json()
    settings = load_settings(llm_provider="anthropic", llm_api_key="test-key")
    invented = explanations.explain(a, settings, llm_call=lambda s, p: "There is a 73% chance of a landslide within 6 hours.")
    assert invented["method"] == "template" and "rejected" in invented["llm_note"]
    tier_only = explanations.explain(a, settings, llm_call=lambda s, p: f"The rule engine rated this {a['risk_tier']}.")
    assert tier_only["method"] == "llm"
    def boom(s, p):
        raise TimeoutError()
    failed = explanations.explain(a, settings, llm_call=boom)
    assert failed["method"] == "template" and "failed" in failed["llm_note"]


def test_assessment_detail_includes_evidence_and_changes(client, auth):
    apply(client, auth["analyst"], "rapid_river_rise")
    items = client.get("/api/assessments?site_id=SNP-05&hazard=flash_flood&limit=2", headers=auth["viewer"]).json()["items"]
    a = client.get(f"/api/assessments/{items[0]['id']}", headers=auth["viewer"]).json()
    assert a["risk_tier"] == "HIGH"
    assert a["evidence_observations"] and a["changes"]["items"]
    assert any("→ HIGH" in i for i in a["changes"]["items"])
    assert a["score_note"].startswith("Ordinal")
