"""UTC time helpers. All timestamps are stored as ISO-8601 UTC strings ending in 'Z'.

`set_frozen_now` exists so tests can pin the clock deterministically.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

_frozen: datetime | None = None


def now() -> datetime:
    return _frozen if _frozen is not None else datetime.now(timezone.utc).replace(microsecond=0)


def set_frozen_now(value: datetime | None) -> None:
    global _frozen
    _frozen = value.astimezone(timezone.utc).replace(microsecond=0) if value else None


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def now_iso() -> str:
    return iso(now())


def parse(value: str) -> datetime:
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        raise ValueError("timestamp must include a timezone (use UTC, e.g. 2026-10-28T10:00:00Z)")
    return dt.astimezone(timezone.utc)


def age_seconds(ts: str, ref: datetime | None = None) -> float:
    return ((ref or now()) - parse(ts)).total_seconds()


__all__ = ["now", "now_iso", "iso", "parse", "age_seconds", "set_frozen_now", "timedelta"]
