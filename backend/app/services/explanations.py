"""Plain-language explanations of a structured assessment.

* Default: a deterministic template built only from the assessment payload.
* Optional: an LLM provider (LLM_PROVIDER=anthropic + LLM_API_KEY). The model
  receives only the structured evidence and is instructed not to add facts.
  Its output then passes a grounding check — every number it mentions must
  appear in the evidence — otherwise it is discarded and the template is used.
The LLM never computes risk; the tier always comes from the rule engine.
"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from typing import Callable

from ..config import Settings

_NUM = re.compile(r"(?<![\w.])-?\d+(?:\.\d+)?")
MAX_LLM_CHARS = 1200
_TIER_WORDS = {"low": "LOW", "elevated": "ELEVATED", "high": "HIGH", "insufficient": "INSUFFICIENT_DATA"}
# A tier stated about the overall risk/tier/assessment, e.g. "the risk tier is LOW", "rated HIGH".
_TIER_CLAIM = re.compile(r"\b(?:risk|tier|rated|assessment|assessed)\b[^.\n]{0,40}?\b(low|elevated|high|insufficient)\b", re.I)

DISCLAIMER = ("Explanation generated from recorded evidence only. Not an official warning. "
              "Thresholds are uncalibrated demonstration settings.")


def evidence_for_llm(a: dict) -> dict:
    return {
        "site": a["site_name"], "hazard": a["hazard_label"], "risk_tier": a["risk_tier"],
        "tier_is_lower_bound": a["tier_is_lower_bound"], "max_possible_tier": a["max_possible_tier"],
        "reliability": a["reliability"], "reliability_notes": a["reliability_notes"], "assessed_at": a["assessed_at"],
        "data_origin": a["data_origin"], "rule_version": a["rule_version"],
        "factors": [{k: f[k] for k in ("label", "value", "unit", "status", "level", "threshold", "as_of")} for f in a["factors"]],
        "missing_inputs": a["missing_inputs"], "approved_review_steps": a["review_steps"],
    }


def template_explanation(a: dict) -> str:
    lines = [a["summary"]]
    for f in a["factors"]:
        if f["value"] is None:
            lines.append(f"• {f['label']}: no usable data ({f['status']}).")
        else:
            stale = " — STALE" if f["status"] == "stale" else (" — incomplete coverage" if f["status"] == "incomplete" else "")
            lines.append(f"• {f['label']}: {f['value']:g} {f['unit']} at {f['as_of']} → {f['level']} "
                         f"(demo thresholds: {f['threshold']}){stale}.")
    if a["tier_is_lower_bound"]:
        lines.append(f"Because inputs are missing or incomplete, the tier could be as high as {a['max_possible_tier']}.")
    if a["data_origin"] in ("SIMULATED", "MIXED"):
        lines.append("Evidence includes SIMULATED readings — this is a demonstration, not a real event.")
    lines.append("Suggested review steps (demo playbook): " + " ".join(f"{i}. {s}" for i, s in enumerate(a["review_steps"], 1)))
    return "\n".join(lines)


def grounded(text: str, evidence: dict) -> tuple[bool, list[str]]:
    allowed = {_norm(n) for n in _NUM.findall(json.dumps(evidence))}
    allowed |= {str(i) for i in range(1, len(evidence.get("approved_review_steps", [])) + 1)}
    unsupported = sorted({n for n in _NUM.findall(text) if _norm(n) not in allowed})
    return (not unsupported, unsupported)


def contradicts_tier(text: str, tier: str) -> list[str]:
    """Tier words the text attaches to the overall risk that differ from the engine's tier (HDEWS-016)."""
    claimed = {_TIER_WORDS[m.group(1).lower()] for m in _TIER_CLAIM.finditer(text)}
    return sorted(c for c in claimed if c != tier)


def _norm(n: str) -> str:
    try:
        return f"{float(n):g}"
    except ValueError:
        return n


def _anthropic_call(settings: Settings, prompt: str) -> str:  # pragma: no cover - needs network + key
    body = json.dumps({
        "model": settings.llm_model or "claude-sonnet-5-5",
        "max_tokens": 400,
        "system": ("You explain disaster-risk assessments to trained reviewers. Use ONLY the JSON evidence provided. "
                   "Do not add measurements, probabilities, lead times, forecasts or instructions. Do not change the risk "
                   "tier. Mention missing or stale data explicitly. Plain text, at most 120 words."),
        "messages": [{"role": "user", "content": prompt}],
    }).encode()
    req = urllib.request.Request("https://api.anthropic.com/v1/messages", data=body, method="POST", headers={
        "content-type": "application/json", "x-api-key": settings.llm_api_key, "anthropic-version": "2023-06-01"})
    with urllib.request.urlopen(req, timeout=settings.llm_timeout_s) as resp:
        data = json.loads(resp.read())
    return "".join(block.get("text", "") for block in data.get("content", []))


def explain(a: dict, settings: Settings, llm_call: Callable[[Settings, str], str] | None = None) -> dict:
    template = template_explanation(a)
    result = {"method": "template", "text": template, "disclaimer": DISCLAIMER,
              "evidence_observation_ids": a["evidence_observation_ids"], "assessment_id": a.get("id"), "llm_note": None}
    if settings.llm_provider != "anthropic" or not settings.llm_api_key:
        result["llm_note"] = "LLM provider not configured; deterministic template used."
        return result
    evidence = evidence_for_llm(a)
    call = llm_call or _anthropic_call
    try:
        text = call(settings, "Explain this assessment:\n" + json.dumps(evidence, indent=1))
        if not isinstance(text, str):
            raise TypeError("provider returned a non-text response")
        text = text.strip()
    except Exception as exc:  # any provider failure must leave the app usable (HDEWS-015)
        # Only the exception type is reported: messages can contain request details.
        result["llm_note"] = f"LLM call failed ({type(exc).__name__}); deterministic template used."
        return result
    if not text:
        result["llm_note"] = "LLM returned an empty response; deterministic template used."
        return result
    if len(text) > MAX_LLM_CHARS:
        result["llm_note"] = f"LLM output rejected: longer than {MAX_LLM_CHARS} characters; deterministic template used."
        return result
    ok, unsupported = grounded(text, evidence)
    if not ok:
        result["llm_note"] = ("LLM output rejected by grounding check (numbers not present in evidence: "
                              f"{', '.join(unsupported[:5])}); deterministic template used.")
        return result
    wrong = contradicts_tier(text, a["risk_tier"])
    if wrong:
        result["llm_note"] = (f"LLM output rejected: it states a risk tier ({', '.join(wrong)}) that differs from the "
                              f"rule engine's {a['risk_tier']}; deterministic template used.")
        return result
    result.update({"method": "llm", "text": text, "llm_note": f"Generated by {settings.llm_model or 'claude-sonnet-5-5'}; "
                   "passed numeric grounding check."})
    return result
