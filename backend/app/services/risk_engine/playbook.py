"""Predefined review steps.

DEMO PLAYBOOK — written for the prototype to illustrate the workflow. It is not an
authority-approved SOP. Before any operational use, replace these steps with the
procedures approved by the responsible disaster-management authority.
"""
from __future__ import annotations

PLAYBOOK_VERSION = "demo-playbook-v0.1 (NOT an approved SOP)"

_DATA_STEPS = [
    "Check sensor connectivity and power status for the stale or missing inputs listed in this assessment.",
    "Request a manual reading or field observation for the missing inputs through the normal reporting channel.",
    "Consult official rainfall and river products (e.g. IMD, CWC, state authority bulletins) for the area.",
]

_STEPS = {
    ("landslide", "HIGH"): [
        "Review the rainfall, soil-moisture and displacement evidence and their timestamps in this assessment.",
        "Compare with the latest official landslide / heavy-rainfall advisories for the district.",
        "Request field verification of the monitored slope by the designated field team.",
        "Decide whether to escalate to the duty officer under the authority-approved SOP.",
    ],
    ("landslide", "ELEVATED"): [
        "Review contributing indicators and confirm sensor health.",
        "Increase review frequency for this site while conditions persist.",
        "Check official rainfall forecasts for the next 24 hours.",
    ],
    ("flash_flood", "HIGH"): [
        "Review river-stage level and rate-of-rise evidence and their timestamps in this assessment.",
        "Cross-check with upstream gauges and official river or flood bulletins where available.",
        "Request visual confirmation of river conditions at the site by the designated field team.",
        "Decide whether to escalate to the duty officer under the authority-approved SOP.",
    ],
    ("flash_flood", "ELEVATED"): [
        "Review rainfall intensity and river trend; confirm the river-stage sensor is reporting.",
        "Increase review frequency for this site while conditions persist.",
        "Check official nowcasts and rainfall forecasts for the upstream catchment.",
    ],
}


def review_steps(hazard: str, tier: str, reliability: str) -> list[str]:
    steps: list[str] = []
    if tier == "INSUFFICIENT_DATA":
        return list(_DATA_STEPS)
    steps.extend(_STEPS.get((hazard, tier), []))
    if reliability in ("DEGRADED", "POOR"):
        steps.extend(_DATA_STEPS[:2])
    if not steps:
        steps.append("No review action required; continue routine monitoring.")
    return steps
