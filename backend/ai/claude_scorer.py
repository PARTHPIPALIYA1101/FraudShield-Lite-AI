"""Claude-backed fraud scoring engine (AsyncAnthropic; Scorer protocol; same flow as Gemini)."""

import logging
import time

import anthropic

from config import settings
from models import FraudAssessment
from ai import cache_manager, prompt_builder, response_parser
# ScoringError + api_failure_assessment are provider-neutral; re-exported here so
# existing imports `from ai.claude_scorer import ...` keep working.
from ai.base import ScoringError, api_failure_assessment  # noqa: F401

logger = logging.getLogger("fraudshield.scorer.claude")


class ClaudeScorer:
    """Stateless scorer wrapping the Anthropic async client + cache."""

    def __init__(self) -> None:
        # base_url -> proxy; max_retries rides out transient 429/5xx; timeout caps an attempt.
        self.client = anthropic.AsyncAnthropic(
            api_key=settings.ANTHROPIC_API_KEY,
            base_url=settings.ANTHROPIC_BASE_URL,
            max_retries=2,
            timeout=30.0,
        )
        self.model = settings.ANTHROPIC_MODEL
        self.max_tokens = 1000

    async def score_transaction(
        self,
        transaction: dict,
        user_context: dict,
        merchant_context: dict,
        feedback_context: str | None,
    ) -> FraudAssessment:
        """Score one transaction (cache hit or fresh call); raises ScoringError on hard failure."""
        # 1. Cache check (per-transaction-id key; hits only on a retry of the same id).
        txn_id = transaction.get("id") or transaction.get("transaction_id")
        cache_key = cache_manager.build_cache_key(transaction, user_context)
        cached = await cache_manager.get(cache_key)
        if cached is not None:
            logger.info("txn=%s cache_key=%s cache=HIT llm_called=False (retry of same id)", txn_id, cache_key)
            return FraudAssessment(**cached, cache_hit=True, inference_ms=0)
        logger.info("txn=%s cache_key=%s cache=MISS llm_called=True (fresh evaluation)", txn_id, cache_key)

        # 2. Build the per-transaction prompt.
        user_prompt = prompt_builder.build(transaction, user_context, merchant_context, feedback_context)

        # 3. Call Claude (async, timed).
        start = time.monotonic()
        try:
            response = await self.client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                system=prompt_builder.FRAUD_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_prompt}],
            )
        except anthropic.APIError as exc:
            # Covers auth/rate-limit/connection/status errors after SDK retries.
            raise ScoringError(f"Anthropic API error: {exc}") from exc
        except Exception as exc:  # noqa: BLE001 - last-resort guard
            raise ScoringError(f"Unexpected scoring failure: {exc}") from exc
        inference_ms = int((time.monotonic() - start) * 1000)

        # 4. Extract text + parse (parser never raises), then stamp per-call metadata.
        assessment = response_parser.parse(self._extract_text(response))
        assessment.inference_ms = inference_ms
        assessment.cache_hit = False
        assessment.ai_model_used = self.model

        # 5. Cache under the txn id (best-effort) so a retry reuses this result.
        await cache_manager.set(cache_key, assessment.model_dump())

        return assessment

    @staticmethod
    def _extract_text(response: "anthropic.types.Message") -> str:
        """Concatenate the text content blocks of the Messages API response."""
        parts: list[str] = []
        for block in getattr(response, "content", []) or []:
            text = getattr(block, "text", None)
            if text:
                parts.append(text)
        return "".join(parts).strip()

    async def aclose(self) -> None:
        """Close the underlying async HTTP client (called on shutdown)."""
        await self.client.close()


# Module-level singleton so the HTTP connection pool is shared across calls.
scorer = ClaudeScorer()


# Manual test harness (makes REAL API calls): python -c "from ai.claude_scorer import test_score; test_score()"
def test_score() -> None:
    """Score three hand-built cases and print results (sync wrapper around the async scorer)."""
    import asyncio

    cases = [
        {
            "name": "A) Normal small purchase -> expect APPROVE",
            "txn": {
                "id": "TXN-normal", "user_id": "user_1", "amount": 85.0,
                "merchant": "Starbucks", "is_foreign_merchant": False,
                "location": "Mumbai, IN", "timestamp": "2026-06-27T13:30:00Z",
            },
            "user": {"txn_count_1h": 1, "txn_count_24h": 3, "avg_amount": 90.0,
                     "top_merchants": ["Starbucks", "Amazon", "Uber"]},
            "merchant": {"fraud_rate": 0.01, "is_first_visit": False},
            "feedback": None,
        },
        {
            "name": "B) High amount, foreign, 2AM, new merchant -> expect DECLINE",
            "txn": {
                "id": "TXN-suspect", "user_id": "user_2", "amount": 8500.0,
                "merchant": "LuxuryWatchesParis", "is_foreign_merchant": True,
                "location": "Paris, FR", "timestamp": "2026-06-27T02:10:00Z",
            },
            "user": {"txn_count_1h": 1, "txn_count_24h": 2, "avg_amount": 120.0,
                     "top_merchants": ["Amazon", "Flipkart"]},
            "merchant": {"fraud_rate": 0.18, "is_first_visit": True},
            "feedback": "Analyst previously confirmed 1 fraud case for this user.",
        },
        {
            "name": "C) Medium velocity burst -> expect REVIEW",
            "txn": {
                "id": "TXN-velocity", "user_id": "user_3", "amount": 600.0,
                "merchant": "OnlineGameStore", "is_foreign_merchant": False,
                "location": "Delhi, IN", "timestamp": "2026-06-27T22:05:00Z",
            },
            "user": {"txn_count_1h": 6, "txn_count_24h": 11, "avg_amount": 150.0,
                     "top_merchants": ["Swiggy", "Zomato"]},
            "merchant": {"fraud_rate": 0.06, "is_first_visit": True},
            "feedback": None,
        },
    ]

    async def run() -> None:
        for c in cases:
            print("\n" + "=" * 70)
            print(c["name"])
            print("-" * 70)
            try:
                a = await scorer.score_transaction(
                    c["txn"], c["user"], c["merchant"], c["feedback"]
                )
                print(f"  fraud_score : {a.fraud_score}")
                print(f"  decision    : {a.decision}")
                print(f"  confidence  : {a.confidence}")
                print(f"  inference_ms: {a.inference_ms}  cache_hit: {a.cache_hit}")
                print(f"  model       : {a.ai_model_used}")
                print(f"  patterns    : {a.patterns_matched}")
                for rf in a.risk_factors:
                    print(f"    - [{rf.severity}] {rf.factor}: {rf.detail}")
                print(f"  explanation : {a.explanation}")
            except ScoringError as exc:
                print(f"  SCORING ERROR: {exc}")
        await scorer.aclose()

    asyncio.run(run())


if __name__ == "__main__":
    test_score()
