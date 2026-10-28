"""Data-source registry with health derived from what has actually been received."""
from __future__ import annotations

from .. import clock
from ..db import Tx


def list_with_health(tx: Tx) -> list[dict]:
    out = []
    for s in tx.all("SELECT * FROM data_sources ORDER BY id"):
        s.pop("ingest_key_hash", None)
        stats = tx.one("SELECT COUNT(*) AS n, MAX(received_at) AS last_received FROM observations WHERE source_id = ?",
                       (s["id"],))
        sensors = tx.all("SELECT id, expected_interval_s FROM sensors WHERE source_id = ?", (s["id"],))
        s["observation_count"] = stats["n"]
        s["last_received_at"] = stats["last_received"]
        s["sensor_count"] = len(sensors)
        s["enabled"] = bool(s["enabled"])
        if s["health_status"] == "NOT_CONFIGURED":
            pass
        elif sensors:
            s["health_status"] = _health(s["last_received_at"], min(x["expected_interval_s"] for x in sensors))
            s["last_success_at"] = s["last_received_at"]
        elif s["access_mode"] == "push_api":
            s["health_status"] = _health(s["last_received_at"], 900) if s["last_received_at"] else "UNKNOWN"
        out.append(s)
    return out


def _health(last: str | None, interval_s: int) -> str:
    if not last:
        return "UNAVAILABLE"
    age = clock.age_seconds(last)
    if age <= 3 * interval_s:
        return "HEALTHY"
    if age <= 6 * 3600:
        return "STALE"
    return "UNAVAILABLE"
