"""Baseline risk engine.

Produces a structured, explainable assessment for one site and one hazard.
Key safety behaviours:

* Risk tier and data reliability are separate outputs.
* If a critical input is missing/stale (reliability POOR) and the available
  evidence alone scores LOW, the tier is INSUFFICIENT_DATA — never "LOW".
* If the available evidence already scores ELEVATED/HIGH while inputs are
  missing, that tier is kept and labelled as a lower bound.
* `max_possible_tier` shows how far missing inputs could move the result.
* Scores are ordinal demo points, not probabilities.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from ... import clock
from .config import RULE_VERSION, THRESHOLD_STATUS
from .features import Indicator, SensorHealth
from .playbook import PLAYBOOK_VERSION, review_steps
from .rules import HAZARD_LABELS, RULES, Factor, evaluate_factor

TIER_ORDER = {"INSUFFICIENT_DATA": -1, "LOW": 0, "ELEVATED": 1, "HIGH": 2}


def tier_for_score(score: int, cfg: dict) -> str:
    if score >= cfg["tiers"]["high_min_score"]:
        return "HIGH"
    if score >= cfg["tiers"]["elevated_min_score"]:
        return "ELEVATED"
    return "LOW"


class MLModelInterface:
    """Pluggable interface for a future, validated ML model.

    No ML model is registered in this prototype: none has been trained or
    validated on labelled event data. A registered model must expose
    `name`, `version`, `validated` (bool) and `predict(features) -> dict`.
    Unvalidated models are refused so they cannot drive assessments.
    """

    _registry: dict[str, Any] = {}

    @classmethod
    def register(cls, hazard: str, model: Any) -> None:
        if not getattr(model, "validated", False):
            raise ValueError("Refusing to register an ML model that has not been validated on labelled data.")
        cls._registry[hazard] = model

    @classmethod
    def get(cls, hazard: str) -> Any | None:
        return cls._registry.get(hazard)

    @classmethod
    def clear(cls) -> None:
        cls._registry.clear()


def assess(site: dict, hazard: str, indicators: dict[str, Indicator], health: dict[str, SensorHealth],
           cfg: dict, ref: datetime | None = None, previous: dict | None = None) -> dict:
    if hazard not in RULES:
        raise ValueError(f"unsupported hazard '{hazard}'")
    ref = ref or clock.now()
    factors: list[Factor] = [evaluate_factor(rule, indicators.get(rule.key), cfg) for rule in RULES[hazard]]
    score = sum(f.points for f in factors)
    computed_tier = tier_for_score(score, cfg)

    missing = [f for f in factors if f.status in ("missing", "stale")]
    critical_missing = [f for f in missing if f.critical]
    degraded_notes: list[str] = []
    for f in factors:
        if f.status == "incomplete":
            degraded_notes.append(f"{f.label}: incomplete sample coverage.")
        if f.status == "stale":
            degraded_notes.append(f"{f.label}: sensor stale (last data {f.as_of}).")
        if f.status == "missing":
            degraded_notes.append(f"{f.label}: no usable data.")
    used_sensor_ids = {indicators[f.key].sensor_id for f in factors if f.key in indicators}
    for h in health.values():
        if h.sensor_id in used_sensor_ids and h.delayed and h.state == "FRESH":
            degraded_notes.append(f"{h.label}: latest reading arrived {int((h.delay_s or 0) // 60)} min after it was observed.")
        if h.sensor_id in used_sensor_ids and h.latest_quality == "suspect":
            degraded_notes.append(f"{h.label}: latest reading flagged suspect.")

    if critical_missing:
        reliability = "POOR"
    elif degraded_notes:
        reliability = "DEGRADED"
    else:
        reliability = "GOOD"

    tier = computed_tier
    lower_bound = False
    if reliability == "POOR":
        if computed_tier == "LOW":
            tier = "INSUFFICIENT_DATA"
        else:
            lower_bound = True
    elif any(f.status in ("missing", "stale", "incomplete") for f in factors):
        lower_bound = computed_tier != "HIGH"

    # Headroom: the tier reachable if every missing/stale factor were at its "high" level.
    headroom = sum(f.max_points - f.points for f in factors if f.status in ("missing", "stale", "incomplete"))
    max_possible_tier = tier_for_score(score + headroom, cfg)

    evidence_ids = sorted({i for f in factors for i in f.evidence_ids})
    origins = sorted({o for f in factors for o in f.origins})
    data_origin = "NONE" if not origins else origins[0] if len(origins) == 1 else "MIXED"

    contributing = [f for f in factors if f.points > 0]
    summary = _summary(hazard, tier, reliability, contributing, critical_missing, lower_bound)

    result = {
        "site_id": site["id"],
        "site_name": site["name"],
        "hazard": hazard,
        "hazard_label": HAZARD_LABELS[hazard],
        "risk_tier": tier,
        "computed_tier_from_available_evidence": computed_tier,
        "tier_is_lower_bound": lower_bound,
        "max_possible_tier": max_possible_tier,
        "reliability": reliability,
        "reliability_notes": degraded_notes,
        "score": score,
        "score_note": "Ordinal demonstration points, not a probability.",
        "factors": [f.as_dict() for f in factors],
        "contributing_factors": [f.key for f in contributing],
        "missing_inputs": [{"key": f.key, "label": f.label, "status": f.status, "critical": f.critical} for f in missing],
        "assessed_at": clock.iso(ref),
        "rule_version": RULE_VERSION,
        "threshold_status": THRESHOLD_STATUS,
        "model": {"type": "baseline_rules", "ml_model": None,
                  "note": "No ML model is registered; no model has been validated on labelled event data."},
        "evidence_observation_ids": evidence_ids,
        "data_origin": data_origin,
        "review_steps": review_steps(hazard, tier, reliability),
        "playbook_version": PLAYBOOK_VERSION,
        "summary": summary,
    }
    result["changes"] = diff_assessments(previous, result)
    return result


def _summary(hazard: str, tier: str, reliability: str, contributing: list[Factor], critical_missing: list[Factor],
             lower_bound: bool) -> str:
    name = HAZARD_LABELS[hazard]
    if tier == "INSUFFICIENT_DATA":
        lacking = ", ".join(f.label.lower() for f in critical_missing)
        return f"{name}: insufficient data to assess — missing or stale critical input(s): {lacking}."
    if contributing:
        drivers = ", ".join(f"{f.label.lower()} ({f.level})" for f in contributing)
        text = f"{name}: {tier} based on {drivers}."
    else:
        text = f"{name}: {tier}; no indicator is above its demo watch threshold."
    if lower_bound:
        text += " Some inputs are missing or incomplete, so this tier may understate the risk."
    if reliability != "GOOD":
        text += f" Data reliability: {reliability}."
    return text


def diff_assessments(previous: dict | None, current: dict) -> dict:
    if not previous:
        return {"previous_assessed_at": None, "items": ["First assessment for this site and hazard."]}
    items: list[str] = []
    if previous["risk_tier"] != current["risk_tier"]:
        items.append(f"Risk tier changed {previous['risk_tier']} → {current['risk_tier']}.")
    if previous["reliability"] != current["reliability"]:
        items.append(f"Data reliability changed {previous['reliability']} → {current['reliability']}.")
    prev = {f["key"]: f for f in previous.get("factors", [])}
    for f in current["factors"]:
        p = prev.get(f["key"])
        if not p:
            continue
        if p["level"] != f["level"]:
            items.append(f"{f['label']}: {p['level']} → {f['level']}.")
        elif p["status"] != f["status"]:
            items.append(f"{f['label']}: data status {p['status']} → {f['status']}.")
    if not items:
        items.append("No change in tier, reliability or indicator levels.")
    return {"previous_assessed_at": previous.get("assessed_at"), "items": items}


def tier_at_least(tier: str, minimum: str) -> bool:
    return TIER_ORDER.get(tier, -1) >= TIER_ORDER[minimum]
