"""Seed the database with the documented demo dataset.

Everything seeded here is either SIMULATED (sensor telemetry), SYNTHETIC
(demo incidents) or IMPORTED public-report summaries with source links.
"""
from __future__ import annotations

import json
import os
import secrets

from . import clock
from .config import REPO_ROOT
from .db import Database
from .security import hash_password, hash_token
from .services import assessments, audit, simulator

DATA = REPO_ROOT / "data" / "sample"

SENSOR_SPECS = {
    "rain_gauge": ("rain_mm", "mm", 900, "Tipping-bucket rain gauge"),
    "soil_moisture": ("soil_moisture_vwc_pct", "% VWC", 900, "Soil-moisture probe (0.5 m)"),
    "extensometer": ("displacement_mm", "mm", 900, "Wire extensometer (cumulative)"),
    "river_stage": ("river_stage_m", "m", 900, "River-stage radar sensor"),
}

DEMO_USERS = [
    ("u_admin", "admin", "Demo Administrator", "admin"),
    ("u_analyst", "analyst", "Demo Analyst", "analyst"),
    ("u_reviewer", "reviewer", "Demo Duty Reviewer", "reviewer"),
    ("u_viewer", "viewer", "Demo Viewer", "viewer"),
]

DATA_SOURCES = [
    dict(id="SIM-GATEWAY", name="Simulated telemetry gateway", source_type="simulator", origin="SIMULATED",
         access_mode="internal", update_cadence="Every 15 min per sensor (simulated)",
         description="Generates synthetic readings for the demo scenarios. Every reading is labelled SIMULATED.",
         attribution="HDEWS prototype", licence="Synthetic data — free to redistribute", url=None, health_status="UNKNOWN"),
    dict(id="FIELD-GATEWAY-01", name="Field telemetry gateway (push API)", source_type="iot_gateway", origin="OBSERVED",
         access_mode="push_api", update_cadence="Device-defined",
         description="Authenticated ingestion endpoint for real sensor gateways. No physical device is connected in this "
                     "prototype; scripts/send_sensor_reading.py exercises the path with test readings.",
         attribution=None, licence=None, url=None, health_status="UNKNOWN"),
    dict(id="INCIDENT-REF", name="Public incident reports (curated)", source_type="incident_inventory", origin="IMPORTED",
         access_mode="file_import", update_cadence="Manual import",
         description="Summaries of publicly reported events with source links (data/sample/incidents.json). "
                     "Not cross-checked against an official inventory.",
         attribution="See each record's source link", licence="Summaries written for HDEWS; follow source terms",
         url=None, health_status="HEALTHY"),
    dict(id="SYNTH-INCIDENTS", name="Synthetic incident records", source_type="incident_inventory", origin="SIMULATED",
         access_mode="file_import", update_cadence="Static",
         description="Fabricated incident records used only to demonstrate the historical explorer.",
         attribution="HDEWS prototype", licence="Synthetic", url=None, health_status="HEALTHY"),
    dict(id="NASA-GPM-IMERG", name="NASA GPM IMERG precipitation", source_type="precipitation", origin="OBSERVED",
         access_mode="external_api", update_cadence="Half-hourly product; latency depends on run (Early/Late/Final)",
         description="Candidate gridded precipitation source (~0.1° grid). Adapter not implemented: requires a NASA "
                     "Earthdata account, download tooling and verification of latency and terms before use.",
         attribution="NASA GES DISC", licence="Verify NASA Earthdata terms before use",
         url="https://gpm.nasa.gov/data/imerg", health_status="NOT_CONFIGURED"),
    dict(id="COPERNICUS-DEM", name="Copernicus DEM (GLO-30)", source_type="terrain", origin="IMPORTED",
         access_mode="file_import", update_cadence="Static",
         description="Candidate terrain source for slope/aspect context. Not yet imported: requires raster download, "
                     "GDAL/rasterio processing and licence review.",
         attribution="Copernicus programme", licence="Verify Copernicus DEM licence terms before use",
         url="https://dataspace.copernicus.eu/explore-data/data-collections/copernicus-contributing-missions/collections-description/COP-DEM",
         health_status="NOT_CONFIGURED"),
    dict(id="SENTINEL-1-2", name="Copernicus Sentinel-1 / Sentinel-2", source_type="satellite", origin="OBSERVED",
         access_mode="external_api", update_cadence="Revisit of several days; cloud cover limits optical use",
         description="Candidate satellite context layers. Not integrated: requires specialist processing and must not "
                     "be used to infer imminent landslides from image change alone.",
         attribution="Copernicus programme", licence="Verify Copernicus terms before use",
         url="https://dataspace.copernicus.eu/", health_status="NOT_CONFIGURED"),
]

INITIAL_SCENARIOS = {
    "SNP-05": "increasing_rainfall",
}


def seed(db: Database, quiet: bool = False) -> dict:
    db.migrate()
    with db.tx() as tx:
        if tx.scalar("SELECT COUNT(*) FROM sites"):
            raise RuntimeError("Database already seeded. Use scripts/reset_db.py to reset it.")
    now = clock.now_iso()
    demo_password = os.environ.get("HDEWS_DEMO_PASSWORD") or "hdews-demo"
    ingest_key = os.environ.get("FIELD_GATEWAY_INGEST_KEY") or secrets.token_urlsafe(24)
    sites_doc = json.loads((DATA / "sites.json").read_text())
    incidents_doc = json.loads((DATA / "incidents.json").read_text())
    with db.tx() as tx:
        for uid, username, display, role in DEMO_USERS:
            tx.insert("users", {"id": uid, "username": username, "display_name": display, "role": role,
                                "password_hash": hash_password(demo_password), "status": "active", "created_at": now})
        for src in DATA_SOURCES:
            row = dict(src, enabled=1, last_success_at=now if src["health_status"] == "HEALTHY" else None,
                       ingest_key_hash=hash_token(ingest_key) if src["access_mode"] == "push_api" else None)
            tx.insert("data_sources", row)
        for s in sites_doc["sites"]:
            tx.insert("sites", {
                "id": s["id"], "name": s["name"], "district": "Rudraprayag", "state": "Uttarakhand",
                "latitude": s["latitude"], "longitude": s["longitude"], "elevation_m": s["elevation_m"],
                "hazards": s["hazards"], "description": s["description"],
                "location_note": "Approximate locality coordinates (±1 km). Simulated monitoring point — no physical sensors installed.",
                "config": s["config"], "sim_state": None, "created_at": now, "updated_at": now,
            })
            for stype in s["sensors"]:
                metric, unit, interval, label = SENSOR_SPECS[stype]
                status = "maintenance" if (s["id"], stype) == ("UKM-06", "extensometer") else "active"
                code = {"rain_gauge": "RAIN", "soil_moisture": "SOIL", "extensometer": "EXT", "river_stage": "RIVER"}[stype]
                tx.insert("sensors", {"id": f"{s['id']}-{code}", "site_id": s["id"],
                                      "sensor_type": stype, "metric": metric, "unit": unit,
                                      "expected_interval_s": interval, "source_id": simulator.SIM_SOURCE_ID,
                                      "status": status, "label": label})
        for inc in incidents_doc["incidents"]:
            tx.insert("incidents", inc)
        audit.record(tx, "system.seeded", "system", None, {
            "sites": len(sites_doc["sites"]), "incidents": len(incidents_doc["incidents"]),
            "note": "Demo dataset: simulated telemetry, synthetic and public-report incidents."})
    admin = {"id": "u_admin", "display_name": "Demo Administrator", "role": "admin"}
    with db.tx() as tx:
        for s in sites_doc["sites"]:
            simulator.apply_scenario(tx, [s["id"]], INITIAL_SCENARIOS.get(s["id"], "normal"), None, admin,
                                     name="Initial demo state")
        assessments.run_all(tx, trigger="seed")
    info = {"demo_password": demo_password, "ingest_key": ingest_key,
            "ingest_key_from_env": bool(os.environ.get("FIELD_GATEWAY_INGEST_KEY"))}
    if not quiet:
        print("HDEWS demo data seeded.")
        print(f"  Demo accounts: admin / analyst / reviewer / viewer — password: {demo_password}")
        if not info["ingest_key_from_env"]:
            print(f"  FIELD-GATEWAY-01 ingestion key (shown once): {ingest_key}")
    return info
