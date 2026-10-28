"""Ingestion of observations pushed by a field gateway (or any configured push source).

Readings are validated, de-duplicated (idempotency key, and a unique constraint on
sensor + observed time + origin) and stored with origin = the source's origin
(e.g. OBSERVED). Units are taken from the sensor registry, not from the payload,
so a gateway cannot silently change units.
"""
from __future__ import annotations

from datetime import timedelta

from pydantic import BaseModel, Field, field_validator

from .. import clock
from ..db import Tx
from ..security import hash_token
from . import audit

VALID_RANGES = {
    "rain_gauge": (0.0, 200.0),        # mm per reporting interval
    "soil_moisture": (0.0, 100.0),     # % VWC
    "extensometer": (-1000.0, 1000.0),  # mm cumulative
    "river_stage": (0.0, 50.0),        # m
}


class Reading(BaseModel):
    sensor_id: str = Field(min_length=1, max_length=64)
    observed_at: str
    value: float | None
    quality_status: str = "good"
    idempotency_key: str | None = Field(default=None, max_length=128)

    @field_validator("observed_at")
    @classmethod
    def _utc(cls, v: str) -> str:
        dt = clock.parse(v)
        if dt > clock.now() + timedelta(minutes=5):
            raise ValueError("observed_at is in the future")
        return clock.iso(dt)

    @field_validator("quality_status")
    @classmethod
    def _quality(cls, v: str) -> str:
        if v not in ("good", "suspect", "bad", "missing"):
            raise ValueError("quality_status must be good, suspect, bad or missing")
        return v


class IngestBatch(BaseModel):
    readings: list[Reading] = Field(min_length=1, max_length=500)


class IngestAuthError(Exception):
    pass


def authenticate_source(tx: Tx, source_id: str, key: str | None) -> dict:
    source = tx.one("SELECT * FROM data_sources WHERE id = ?", (source_id,))
    if not source or source["access_mode"] != "push_api":
        raise LookupError(source_id)
    if not source["enabled"]:
        raise IngestAuthError("source is disabled")
    if not key or not source["ingest_key_hash"] or hash_token(key) != source["ingest_key_hash"]:
        raise IngestAuthError("invalid ingestion key")
    return source


def ingest(tx: Tx, source: dict, batch: IngestBatch) -> dict:
    now = clock.now_iso()
    accepted, duplicates, rejected = 0, 0, []
    sites_touched: set[str] = set()
    for i, r in enumerate(batch.readings):
        sensor = tx.one("SELECT * FROM sensors WHERE id = ?", (r.sensor_id,))
        if not sensor:
            rejected.append({"index": i, "sensor_id": r.sensor_id, "error": "unknown sensor"})
            continue
        quality = r.quality_status
        lo, hi = VALID_RANGES[sensor["sensor_type"]]
        if r.value is None:
            quality = "missing"
        elif not (lo <= r.value <= hi):
            quality = "bad"  # stored for traceability, excluded from assessment
        if r.idempotency_key and tx.one("SELECT id FROM observations WHERE idempotency_key = ?", (r.idempotency_key,)):
            duplicates += 1
            continue
        exists = tx.one("SELECT id FROM observations WHERE sensor_id = ? AND observed_at = ? AND origin = ?",
                        (r.sensor_id, r.observed_at, source["origin"]))
        if exists:
            duplicates += 1
            continue
        tx.insert("observations", {
            "sensor_id": sensor["id"], "site_id": sensor["site_id"], "source_id": source["id"], "metric": sensor["metric"],
            "value": r.value, "unit": sensor["unit"], "observed_at": r.observed_at, "received_at": now,
            "quality_status": quality, "origin": source["origin"], "provenance": f"Pushed by {source['name']} ({source['id']})",
            "idempotency_key": r.idempotency_key,
        })
        accepted += 1
        sites_touched.add(sensor["site_id"])
    tx.execute("UPDATE data_sources SET last_success_at = ?, health_status = 'HEALTHY' WHERE id = ?", (now, source["id"]))
    audit.record(tx, "ingestion.batch", "data_source", source["id"],
                 {"accepted": accepted, "duplicates": duplicates, "rejected": len(rejected)},
                 {"id": None, "display_name": source["name"], "role": "ingestion"})
    return {"accepted": accepted, "duplicates": duplicates, "rejected": rejected, "sites": sorted(sites_touched)}
