"""Provider-agnostic scoring primitives shared by every LLM backend."""

from typing import Optional, Protocol, runtime_checkable

from config import settings
from models import Confidence, Decision, FraudAssessment


class ScoringError(Exception):
    """Raised on an unrecoverable LLM API failure (after the SDK's own retries)."""


def api_failure_assessment(reason: str, model: Optional[str] = None) -> FraudAssessment:
    """Safe REVIEW/LOW default the consumer persists when the LLM is unreachable."""
    return FraudAssessment(
        fraud_score=0.5,
        decision=Decision.REVIEW,
        confidence=Confidence.LOW,
        risk_factors=[],
        patterns_matched=["manual_review_required"],
        explanation=(
            f"AI scoring unavailable ({reason}). Transaction routed to manual "
            f"review by default. No automated decision was made."
        ),
        ai_model_used=model or settings.ACTIVE_MODEL,
        cache_hit=False,
        inference_ms=0,
    )


@runtime_checkable
class Scorer(Protocol):
    """Structural interface every provider scorer implements."""

    async def score_transaction(
        self,
        transaction: dict,
        user_context: dict,
        merchant_context: dict,
        feedback_context: Optional[str],
    ) -> FraudAssessment:
        ...

    async def aclose(self) -> None:
        ...
