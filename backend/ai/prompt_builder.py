"""Dynamic prompt assembly for the fraud scorer (system prompt + per-txn user prompt)."""

from datetime import datetime
from typing import Optional

from config import settings

# Static system prompt: the JSON contract + calibration rules + few-shot anchors.
FRAUD_SYSTEM_PROMPT = """You are a payment fraud-risk scoring assistant. You estimate the probability that ONE transaction is fraudulent and return it as JSON.

# CALIBRATION (read first — this is the most important part)
The vast majority of real transactions are LEGITIMATE. Your DEFAULT is a LOW score.
Only raise the score when there is concrete, CONVERGING evidence of fraud — that is,
several independent risk signals reinforcing each other. A single unusual-looking
field is NOT fraud. When in doubt, APPROVE.

# How to read each signal (avoid these common mistakes)
- AMOUNT: Only an amount MUCH HIGHER than the user's normal spending is a risk signal
  (roughly 3x their average or more). An amount that is SMALLER than usual is NOT
  suspicious — people make small purchases constantly. A $3 charge from a user who
  averages $5000 is completely normal and must score LOW. NEVER raise the score just
  because the amount is small or because it differs from the average downward.
- VELOCITY: Many transactions in a short window (e.g. 6+ in one hour) is a signal.
  A few per day is normal and is not And too many large amount tranjection in hour shoud be
  decline or in review as per other condition.
- FOREIGN / NEW MERCHANT: Only meaningful when the user has an ESTABLISHED history
  that this transaction clearly breaks. If the user has little or no history, treat
  "new merchant" / "first visit" as UNKNOWN, not as risk — score LOW with LOW
  confidence for SMALL/ORDINARY amounts. New users are not fraudsters by default.
- NEW USER + LARGE AMOUNT: a brand-new user (no spending history) making a LARGE first
  transaction (above ~$100) IS a real risk — a first-time large charge with no baseline
  is a classic stolen-card / account-takeover pattern. Do NOT auto-approve it: score it
  at least REVIEW (>= 0.45), and DECLINE (>= 0.75) for clearly large amounts (~$500+).
  Small first charges (<= $100) are still fine and should APPROVE.
- TIME: Late night (00:00–05:00) is a WEAK signal, and only when combined with others.
- CARD TESTING: a BURST of many tiny charges is suspicious; a SINGLE small charge is not.
- A high-spending user can absolutely make a small purchase. Do not flag it.

# Scoring anchors (fraud_score is 0.0–1.0)
- 0.00–0.15: normal, expected behaviour (ordinary amount; known or plausible merchant).
             THIS IS THE MAJORITY OF TRANSACTIONS.
- 0.15–0.30: mild novelty (new merchant, somewhat higher amount) but nothing alarming → APPROVE.
- 0.30–0.70: genuinely ambiguous — two or more moderate signals together → REVIEW.
- 0.70–1.00: strong, converging fraud evidence (e.g. very high amount + new foreign
             merchant + high velocity + odd hour) → DECLINE.

# Decision thresholds (derive decision from fraud_score)
  < 0.30   -> APPROVE
  0.30–0.70 -> REVIEW
  > 0.70   -> DECLINE

# Output — return ONLY this JSON, no markdown, no prose outside it:
{
  "fraud_score": <float 0.0 to 1.0>,
  "decision": <"APPROVE" | "REVIEW" | "DECLINE">,
  "confidence": <"HIGH" | "MEDIUM" | "LOW">,
  "risk_factors": [
    {"factor": "<name>", "severity": <"HIGH"|"MEDIUM"|"LOW">, "detail": "<one sentence>"}
  ],
  "explanation": "<2-3 sentence plain-English explanation for an analyst>",
  "patterns_matched": ["<pattern1>", "<pattern2>"]
}
If there are no real risk factors, return an empty risk_factors array and a short
explanation saying the transaction looks normal.

# Calibration examples (match this scoring)
- $3 coffee, user avg $5000, domestic, established account → fraud_score 0.05, APPROVE,
  risk_factors []  (small amount is NOT a risk; spending less than usual is normal).
- $120 at Amazon, returning domestic user → fraud_score 0.08, APPROVE.
- $40 from a NEW user with no history, domestic → fraud_score 0.1, APPROVE
  (a small first charge is fine).
- $600 from a NEW user with NO history, domestic → fraud_score 0.6, REVIEW
  (a large first charge with no baseline is risky — do not auto-approve).
- $8000 from a NEW user with NO history, on their FIRST transaction → fraud_score 0.85,
  DECLINE (large first-time charge with no baseline = classic stolen-card pattern).
- $9000 at a brand-new FOREIGN merchant at 3AM, user avg $150, 6 txns in the last hour
  → fraud_score 0.9, DECLINE (many converging signals).
"""


def _parse_hour(timestamp: str) -> int:
    """Hour-of-day (0-23) from an ISO-8601 timestamp; falls back to 12 if unparseable."""
    try:
        ts = timestamp.strip()
        if ts.endswith("Z"):
            ts = ts[:-1] + "+00:00"
        return datetime.fromisoformat(ts).hour
    except (ValueError, AttributeError):
        return 12


def _amount_ratio(amount: float, avg_amount: float) -> float:
    """Amount as a multiple of the user's average. 0 avg -> 1.0 (no signal)."""
    if avg_amount and avg_amount > 0:
        return amount / avg_amount
    return 1.0


def build(
    transaction: dict,
    user_context: dict,
    merchant_context: dict,
    feedback_context: Optional[str],
) -> str:
    """Assemble the per-transaction user prompt (with interpreted, not raw, signals)."""
    # Raw facts (all defensive against missing keys).
    hour = _parse_hour(str(transaction.get("timestamp", "")))
    avg_amount = float(user_context.get("avg_amount", 0.0) or 0.0)
    amount = float(transaction.get("amount", 0.0) or 0.0)
    ratio = _amount_ratio(amount, avg_amount)
    txn_count_1h = int(user_context.get("txn_count_1h", 0) or 0)

    top_merchants = user_context.get("top_merchants") or []
    merchant = transaction.get("merchant", "unknown")
    is_new_merchant = merchant not in top_merchants
    is_foreign = bool(transaction.get("is_foreign_merchant", False))

    fraud_rate = merchant_context.get("fraud_rate")
    fraud_rate_pct = (fraud_rate if fraud_rate is not None else 0.05) * 100

    # No baseline -> novelty signals are uncertainty, not evidence of fraud.
    has_history = avg_amount > 0 or len(top_merchants) > 0

    # Interpret each signal so the model isn't misled by raw numbers.
    new_user_limit = settings.NEW_USER_AMOUNT_LIMIT
    if not has_history:
        if amount <= new_user_limit:
            amount_signal = (
                f"new user with no history; ${amount:.2f} is within the "
                f"${new_user_limit:.0f} new-user limit — low risk"
            )
        else:
            amount_signal = (
                f"NEW user with NO history making a LARGE first charge (${amount:.2f}, "
                f"over the ${new_user_limit:.0f} new-user limit) — elevated risk "
                "(classic stolen-card pattern); do NOT auto-approve"
            )
    elif ratio <= 1.0:
        amount_signal = (
            f"{ratio:.1f}x the user's average — AT OR BELOW their normal spending, "
            "which is NOT a risk signal (a smaller-than-usual purchase is normal)"
        )
    elif ratio < 2.0:
        amount_signal = f"{ratio:.1f}x the user's average — within their normal range"
    elif ratio < 5.0:
        amount_signal = f"{ratio:.1f}x the user's average — moderately above normal"
    else:
        amount_signal = (
            f"{ratio:.1f}x the user's average — SIGNIFICANTLY above normal (risk signal)"
        )

    if not top_merchants:
        merchant_signal = (
            "user has no merchant history yet — treat this merchant as UNKNOWN, "
            "not as a risk"
        )
    elif is_new_merchant:
        merchant_signal = "new merchant for this user (mild signal; weigh with others)"
    else:
        merchant_signal = "a merchant the user has transacted with before (low risk)"

    if txn_count_1h >= 6:
        velocity_signal = f"{txn_count_1h} in the last hour — HIGH velocity (risk signal)"
    elif txn_count_1h >= 3:
        velocity_signal = f"{txn_count_1h} in the last hour — somewhat elevated"
    else:
        velocity_signal = f"{txn_count_1h} in the last hour — normal velocity"

    late_night = 0 <= hour <= 5
    time_signal = (
        f"hour {hour:02d} — late night (weak signal, only matters with others)"
        if late_night
        else f"hour {hour:02d} — normal hours"
    )
    foreign_signal = (
        "foreign merchant"
        + (
            " but the user has no history to break — not a strong signal"
            if not has_history
            else " (weigh against the user's history)"
        )
        if is_foreign
        else "domestic merchant"
    )

    feedback_block = (
        feedback_context.strip()
        if feedback_context and feedback_context.strip()
        else "  No prior feedback available."
    )

    return f"""Score this transaction. Remember: default to a LOW score; only raise it
when MULTIPLE signals converge. A low/normal amount is never suspicious by itself.

TRANSACTION:
  ID:        {transaction.get('id', 'unknown')}
  Amount:    ${amount:.2f}
  Merchant:  {merchant}
  Location:  {transaction.get('location') or 'unknown'}
  Time:      {transaction.get('timestamp', 'unknown')}

USER BASELINE:
  User ID:                  {transaction.get('user_id', 'unknown')}
  Avg amount (30d):         ${avg_amount:.2f}
  Established history?:      {"yes" if has_history else "NO — new/low-history user"}
  Usual merchants:          {", ".join(top_merchants) if top_merchants else "none yet"}

SIGNAL INTERPRETATION (use these, not the raw numbers):
  Amount:    {amount_signal}
  Merchant:  {merchant_signal}
  Velocity:  {velocity_signal}
  Time:      {time_signal}
  Origin:    {foreign_signal}
  Merchant historical fraud rate: {fraud_rate_pct:.1f}%

ANALYST FEEDBACK HISTORY:
{feedback_block}

Return the JSON fraud assessment now.
"""
