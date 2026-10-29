"""Hazard-specific baseline rules.

Each rule turns indicators into scored "factors". A factor records the value,
the threshold that was compared, the points awarded and the evidence used, so the
assessment can explain itself. Points are an ordinal scoring device for the
demonstration rules — they are NOT probabilities.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable

from .features import Indicator


@dataclass
class IndicatorRule:
    key: str
    critical: bool
    watch_points: int
    high_points: int
    thresholds: Callable[[dict], tuple[float, float]]
    threshold_label: Callable[[dict], str]
    transform: Callable[[float, dict], float] = lambda v, cfg: v
    transform_label: str | None = None


@dataclass
class Factor:
    key: str
    label: str
    unit: str
    value: float | None
    compared_value: float | None
    status: str
    level: str  # normal | watch | high | unknown
    points: int
    max_points: int
    critical: bool
    threshold: str
    as_of: str | None
    evidence_ids: list[int] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    origins: list[str] = field(default_factory=list)
    critical_reason: str | None = None

    def as_dict(self) -> dict:
        return self.__dict__.copy()


def _wh(section: str, key: str):
    return lambda cfg: (float(cfg[section][key]["watch"]), float(cfg[section][key]["high"]))


def _wh_label(section: str, key: str, unit: str):
    return lambda cfg: f"watch ≥ {cfg[section][key]['watch']:g} {unit}, high ≥ {cfg[section][key]['high']:g} {unit}"


LANDSLIDE_RULES: list[IndicatorRule] = [
    IndicatorRule("rain_24h_mm", True, 1, 2, _wh("landslide", "rain_24h_mm"), _wh_label("landslide", "rain_24h_mm", "mm")),
    IndicatorRule("rain_1h_mm", False, 1, 2, _wh("landslide", "rain_1h_mm"), _wh_label("landslide", "rain_1h_mm", "mm")),
    IndicatorRule(
        "soil_moisture_pct", True, 1, 2,
        _wh("landslide", "soil_moisture_excess_pct"),
        lambda cfg: (f"excess over site baseline {cfg['landslide']['soil_moisture_baseline_pct']:g}% VWC: "
                     f"watch ≥ +{cfg['landslide']['soil_moisture_excess_pct']['watch']:g}, "
                     f"high ≥ +{cfg['landslide']['soil_moisture_excess_pct']['high']:g} points"),
        transform=lambda v, cfg: v - float(cfg["landslide"]["soil_moisture_baseline_pct"]),
        transform_label="excess over site baseline",
    ),
    # Direct slope-movement evidence is weighted more heavily than antecedent conditions.
    IndicatorRule("displacement_24h_mm", False, 2, 4, _wh("landslide", "displacement_24h_mm"),
                  _wh_label("landslide", "displacement_24h_mm", "mm")),
]

FLASH_FLOOD_RULES: list[IndicatorRule] = [
    IndicatorRule(
        "river_level_m", True, 2, 4,
        lambda cfg: (float(cfg["flash_flood"]["river_warning_level_m"]), float(cfg["flash_flood"]["river_danger_level_m"])),
        lambda cfg: (f"site warning stage {cfg['flash_flood']['river_warning_level_m']:g} m, "
                     f"danger stage {cfg['flash_flood']['river_danger_level_m']:g} m"),
    ),
    IndicatorRule("river_rise_1h_m", False, 1, 2, _wh("flash_flood", "river_rise_1h_m"), _wh_label("flash_flood", "river_rise_1h_m", "m")),
    IndicatorRule("rain_1h_mm", True, 1, 2, _wh("flash_flood", "rain_1h_mm"), _wh_label("flash_flood", "rain_1h_mm", "mm")),
    IndicatorRule("rain_3h_mm", False, 1, 2, _wh("flash_flood", "rain_3h_mm"), _wh_label("flash_flood", "rain_3h_mm", "mm")),
]

RULES = {"landslide": LANDSLIDE_RULES, "flash_flood": FLASH_FLOOD_RULES}

HAZARD_LABELS = {"landslide": "Rainfall-triggered landslide", "flash_flood": "Flash flood"}

INDICATOR_LABELS = {
    "rain_1h_mm": ("Rainfall, last 1 h", "mm"),
    "rain_3h_mm": ("Rainfall, last 3 h", "mm"),
    "rain_24h_mm": ("Rainfall, last 24 h", "mm"),
    "soil_moisture_pct": ("Soil moisture (volumetric)", "% VWC"),
    "displacement_24h_mm": ("Slope displacement, 24 h change", "mm"),
    "river_level_m": ("River stage", "m"),
    "river_rise_1h_m": ("River stage, 1 h change", "m"),
}


def evaluate_factor(rule: IndicatorRule, indicator: Indicator | None, cfg: dict) -> Factor:
    label, unit = INDICATOR_LABELS[rule.key]
    threshold = rule.threshold_label(cfg)
    if indicator is None:
        return Factor(rule.key, label, unit, None, None, "missing", "unknown", 0, rule.high_points, rule.critical,
                      threshold, None, notes=["No sensor configured for this indicator at this site."],
                      critical_reason="documented critical input" if rule.critical else None)
    factor = Factor(rule.key, label, unit, indicator.value, None, indicator.status, "unknown", 0, rule.high_points,
                    rule.critical, threshold, indicator.as_of, list(indicator.evidence_ids), list(indicator.notes),
                    sorted(indicator.origins), "documented critical input" if rule.critical else None)
    if not indicator.usable or not math.isfinite(indicator.value):
        if indicator.value is not None and not math.isfinite(indicator.value):
            factor.status, factor.value = "missing", None
            factor.notes.append("Non-finite value ignored.")
        return factor
    compared = rule.transform(indicator.value, cfg)
    factor.compared_value = round(compared, 2)
    watch, high = rule.thresholds(cfg)
    if compared >= high:
        factor.level, factor.points = "high", rule.high_points
    elif compared >= watch:
        factor.level, factor.points = "watch", rule.watch_points
    else:
        factor.level = "normal"
    return factor
