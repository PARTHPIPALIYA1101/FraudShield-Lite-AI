"""Parse + validate the LLM's raw text into a FraudAssessment (never raises; fails to REVIEW)."""

import json
import re
from typing import Any

from models import (
    Confidence,
    Decision,
    FraudAssessment,
    RiskFactor,
    Severity,
    decision_for_score,
)

# Matches a ```json ... ``` fenced block (group 1) and the outermost {...} object.
_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)
_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)

_VALID_CONFIDENCE = {c.value for c in Confidence}
_VALID_SEVERITY = {s.value for s in Severity}


def _fallback(reason: str) -> FraudAssessment:
    """The safe default when the LLM output can't be trusted -> human review."""
    return FraudAssessment(
        fraud_score=0.5,
        decision=Decision.REVIEW,
        confidence=Confidence.LOW,
        risk_factors=[],
        patterns_matched=[],
        explanation=f"Unable to parse AI response ({reason}). Manual review required.",
        inference_ms=0,
        cache_hit=False,
    )


def _extract_json(raw_text: str) -> str:
    """Strip code fences, then isolate the outermost brace pair (discard stray prose)."""
    cleaned = raw_text.strip()

    fence = _FENCE_RE.search(cleaned)
    if fence:
        cleaned = fence.group(1).strip()

    obj = _OBJECT_RE.search(cleaned)
    if obj:
        cleaned = obj.group(0)

    return cleaned.strip()


def _coerce_confidence(value: Any) -> str:
    """Normalize confidence to a valid enum value; default MEDIUM if unknown."""
    v = str(value).strip().upper()
    return v if v in _VALID_CONFIDENCE else Confidence.MEDIUM.value


def _coerce_risk_factors(value: Any) -> list[RiskFactor]:
    """Build a clean RiskFactor list, skipping malformed entries."""
    if not isinstance(value, list):
        return []
    factors: list[RiskFactor] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        severity = str(item.get("severity", "")).strip().upper()
        if severity not in _VALID_SEVERITY:
            severity = Severity.MEDIUM.value
        factor = str(item.get("factor", "")).strip()
        detail = str(item.get("detail", "")).strip()
        if not factor:
            continue
        factors.append(RiskFactor(factor=factor, severity=severity, detail=detail or factor))
    return factors


def _coerce_patterns(value: Any) -> list[str]:
    """Coerce patterns_matched into a list of non-empty strings."""
    if not isinstance(value, list):
        return []
    return [str(p).strip() for p in value if str(p).strip()]


def parse(raw_text: str) -> FraudAssessment:
    """Parse raw text into a validated FraudAssessment; decision re-derived from score. Never raises."""
    if not raw_text or not raw_text.strip():
        return _fallback("empty response")

    cleaned = _extract_json(raw_text)

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        return _fallback("invalid JSON")

    if not isinstance(data, dict):
        return _fallback("JSON was not an object")

    try:
        score = float(data["fraud_score"])
    except (KeyError, TypeError, ValueError):
        return _fallback("missing or non-numeric fraud_score")

    if not (0.0 <= score <= 1.0):
        score = max(0.0, min(1.0, score))  # clamp rather than reject

    # Decision is authoritative from the score, not the model's text.
    decision = decision_for_score(score)

    explanation = str(data.get("explanation", "")).strip()
    if not explanation:
        explanation = "No explanation provided by the model."

    return FraudAssessment(
        fraud_score=score,
        decision=decision,
        confidence=_coerce_confidence(data.get("confidence", Confidence.MEDIUM.value)),
        risk_factors=_coerce_risk_factors(data.get("risk_factors", [])),
        patterns_matched=_coerce_patterns(data.get("patterns_matched", [])),
        explanation=explanation,
    )
