"""Single entry point that resolves the active LLM scorer (lazy + memoized)."""

from typing import Optional

from config import settings
from ai.base import Scorer, ScoringError, api_failure_assessment  # noqa: F401 re-export

_scorer: Optional[Scorer] = None


def get_scorer() -> Scorer:
    """Return the process-wide scorer for the configured provider (memoized)."""
    global _scorer
    if _scorer is None:
        provider = settings.LLM_PROVIDER.lower().strip()
        if provider == "anthropic":
            from ai.claude_scorer import ClaudeScorer

            _scorer = ClaudeScorer()
        elif provider == "gemini":
            from ai.gemini_scorer import GeminiScorer

            _scorer = GeminiScorer()
        else:
            raise ValueError(
                f"Unknown LLM_PROVIDER '{settings.LLM_PROVIDER}'. Use 'gemini' or 'anthropic'."
            )
    return _scorer


async def close_scorer() -> None:
    """Close the active scorer's client on app shutdown."""
    global _scorer
    if _scorer is not None:
        await _scorer.aclose()
        _scorer = None
