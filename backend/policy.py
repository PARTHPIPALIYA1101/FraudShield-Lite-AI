"""Deterministic business-policy overrides applied on top of the AI assessment.

The LLM is a calibrated estimator, not a hard guarantee. These rules enforce
non-negotiable business limits — e.g. a brand-new user (no history) cannot have a
large first transaction auto-approved, since a first-time large charge with no
baseline is a classic stolen-card / card-testing pattern.
"""

import logging

from config import settings
from models import FraudAssessment, RiskFactor, decision_for_score

logger = logging.getLogger("fraudshield.policy")

# Score floors the rule raises the assessment to (REVIEW band / DECLINE band).
_REVIEW_FLOOR = 0.45
_DECLINE_FLOOR = 0.75


def is_new_user(user_context: dict) -> bool:
    """True for a user with no established behavioral baseline yet (cold start)."""
    avg = float(user_context.get("avg_amount", 0) or 0)
    merchants = user_context.get("top_merchants") or []
    return avg <= 0.0 and not merchants


def apply_policies(assessment: FraudAssessment, transaction: dict, user_context: dict) -> FraudAssessment:
    """Enforce hard rules on top of the AI score (currently: the new-user amount limit)."""
    amount = float(transaction.get("amount", 0) or 0)
    limit = settings.NEW_USER_AMOUNT_LIMIT

    if is_new_user(user_context) and amount > limit:
        # No history to justify a large charge -> never auto-approve. Big amounts
        # route to user confirmation (DECLINE band); smaller ones to review.
        floor = _DECLINE_FLOOR if amount >= limit * 5 else _REVIEW_FLOOR
        if assessment.fraud_score < floor:
            old = assessment.fraud_score
            assessment.fraud_score = floor
            assessment.decision = decision_for_score(floor).value
            assessment.risk_factors.append(
                RiskFactor(
                    factor="new_user_amount_limit",
                    severity="HIGH" if floor >= _DECLINE_FLOOR else "MEDIUM",
                    detail=(
                        f"New user with no history charging ${amount:.2f}, over the "
                        f"${limit:.0f} first-transaction limit."
                    ),
                )
            )
            if "new_user_over_limit" not in assessment.patterns_matched:
                assessment.patterns_matched.append("new_user_over_limit")
            assessment.explanation = (assessment.explanation or "").strip() + (
                f" Policy: a new user with no history cannot be auto-approved above "
                f"${limit:.0f}; this ${amount:.2f} charge was routed for verification."
            )
            logger.info(
                "Policy new-user-limit applied to txn %s: score %.2f -> %.2f",
                transaction.get("id"), old, floor,
            )
    return assessment
