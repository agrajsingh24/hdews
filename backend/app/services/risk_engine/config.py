"""Baseline rule configuration.

EVERY NUMBER IN THIS FILE IS A DEMONSTRATION SETTING. None of these thresholds
has been calibrated against observed landslide or flood events, and none of them
should be used as operational guidance. Site-specific overrides are stored in
`sites.config` and merged on top of these defaults.
"""
from __future__ import annotations

import copy
from typing import Any

RULE_VERSION = "baseline-rules-v0.1-demo"
THRESHOLD_STATUS = "EXPERIMENTAL_DEMO_SETTINGS_NOT_CALIBRATED"

DEFAULT_CONFIG: dict[str, Any] = {
    "freshness": {
        # A sensor is STALE when its newest reading is older than this multiple of
        # its expected reporting interval, and OFFLINE after `offline_after_s`.
        "stale_multiplier": 3,
        "offline_after_s": 6 * 3600,
        # A reading is DELAYED when it reached HDEWS this many intervals after it was observed.
        "delay_multiplier": 2,
    },
    "rain": {
        # Accumulations built from fewer than this fraction of expected samples are INCOMPLETE.
        "min_coverage": 0.75,
    },
    "landslide": {
        "rain_24h_mm": {"watch": 50.0, "high": 100.0},
        "rain_1h_mm": {"watch": 15.0, "high": 30.0},
        "soil_moisture_baseline_pct": 28.0,
        "soil_moisture_excess_pct": {"watch": 8.0, "high": 15.0},
        "displacement_24h_mm": {"watch": 2.0, "high": 5.0},
    },
    "flash_flood": {
        "river_warning_level_m": 3.0,
        "river_danger_level_m": 4.0,
        "river_rise_1h_m": {"watch": 0.3, "high": 0.6},
        "rain_1h_mm": {"watch": 15.0, "high": 30.0},
        "rain_3h_mm": {"watch": 30.0, "high": 60.0},
    },
    "tiers": {"elevated_min_score": 2, "high_min_score": 4},
    "alerting": {
        # Candidate HAZARD alerts are created at or above this tier.
        "hazard_alert_min_tier": "HIGH",
        # A DATA_QUALITY candidate alert is raised when a critical input is missing
        # while observed 1-hour rainfall at the site is at or above this value.
        "data_quality_alert_rain_1h_mm": 10.0,
    },
}


def merge_config(site_config: dict | None) -> dict:
    merged = copy.deepcopy(DEFAULT_CONFIG)
    _deep_merge(merged, site_config or {})
    return merged


def _deep_merge(base: dict, override: dict) -> None:
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value


def validate_site_overrides(overrides: dict) -> list[str]:
    """Return a list of validation errors for admin-edited site thresholds."""
    errors: list[str] = []
    allowed = {"landslide", "flash_flood"}
    for section in overrides:
        if section not in allowed:
            errors.append(f"unknown section '{section}' (allowed: {sorted(allowed)})")
    merged = merge_config(overrides)
    for hazard in ("landslide", "flash_flood"):
        for key, value in merged[hazard].items():
            if isinstance(value, dict):
                w, h = value.get("watch"), value.get("high")
                if not all(isinstance(x, (int, float)) and x >= 0 for x in (w, h)):
                    errors.append(f"{hazard}.{key}: watch/high must be non-negative numbers")
                elif w >= h:
                    errors.append(f"{hazard}.{key}: watch ({w}) must be lower than high ({h})")
            elif not isinstance(value, (int, float)) or value < 0:
                errors.append(f"{hazard}.{key}: must be a non-negative number")
    ff = merged["flash_flood"]
    if isinstance(ff["river_warning_level_m"], (int, float)) and isinstance(ff["river_danger_level_m"], (int, float)):
        if ff["river_warning_level_m"] >= ff["river_danger_level_m"]:
            errors.append("flash_flood: river_warning_level_m must be lower than river_danger_level_m")
    return errors
