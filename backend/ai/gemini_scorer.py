"""Google Gemini (AI Studio) fraud scoring engine (native JSON mode; Scorer protocol)."""

import logging
import time
from typing import Optional

import google.generativeai as genai

from config import settings
from models import FraudAssessment
from ai import cache_manager, prompt_builder, response_parser
from ai.base import ScoringError, api_failure_assessment  # noqa: F401 (re-export)

logger = logging.getLogger("fraudshield.scorer.gemini")


class GeminiScorer:
    """Stateless scorer wrapping the Gemini async client + bucketed cache."""

    def __init__(self) -> None:
        genai.configure(api_key=settings.GOOGLE_API_KEY)
        self.model_name = settings.GEMINI_MODEL
        # system_instruction pins the rubric; response_mime_type forces valid JSON.
        self.model = genai.GenerativeModel(
            model_name=self.model_name,
            system_instruction=prompt_builder.FRAUD_SYSTEM_PROMPT,
            generation_config={
                "response_mime_type": "application/json",
                "max_output_tokens": 1000,
                "temperature": 0.2,
            },
        )

    async def score_transaction(
        self,
        transaction: dict,
        user_context: dict,
        merchant_context: dict,
        feedback_context: Optional[str],
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

        # 3. Call Gemini (async, timed).
        start = time.monotonic()
        try:
            response = await self.model.generate_content_async(user_prompt)
        except Exception as exc:  # google SDK raises a variety of error types
            raise ScoringError(f"Gemini API error: {exc}") from exc
        inference_ms = int((time.monotonic() - start) * 1000)

        # 4. Extract text + parse (parser never raises), then stamp per-call metadata.
        assessment = response_parser.parse(self._extract_text(response))
        assessment.inference_ms = inference_ms
        assessment.cache_hit = False
        assessment.ai_model_used = self.model_name

        # 5. Cache under the txn id (best-effort) so a retry reuses this result.
        await cache_manager.set(cache_key, assessment.model_dump())

        return assessment

    @staticmethod
    def _extract_text(response) -> str:
        """Pull text from a Gemini response; walk candidates/parts if response.text raises."""
        try:
            text = response.text
            if text:
                return text.strip()
        except Exception:
            pass

        parts: list[str] = []
        for cand in getattr(response, "candidates", []) or []:
            content = getattr(cand, "content", None)
            for part in getattr(content, "parts", []) or []:
                t = getattr(part, "text", None)
                if t:
                    parts.append(t)
        return "".join(parts).strip()

    async def aclose(self) -> None:
        """No persistent client to close for google-generativeai; no-op for parity."""
        return None


# Manual test harness (makes REAL API calls): python -c "from ai.gemini_scorer import test_score; test_score()"
def test_score() -> None:
    """Score three hand-built cases through Gemini and print results."""
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

    scorer = GeminiScorer()

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
