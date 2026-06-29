"""Redis cache for the AI assessment, keyed on transaction_id (idempotency, not dedup).

Every transaction is a new financial event, so the key is the unique transaction_id:
a brand-new txn always misses (fresh LLM eval); only a retry/redelivery of the SAME
id reuses the result. (It used to bucket on merchant+amount, which wrongly reused a
stale assessment for two different transactions — that was a fraud-correctness bug.)
"""

import json
import logging
from typing import Optional

from config import settings
from redis_client import get_redis

logger = logging.getLogger("fraudshield.cache")

_CACHE_PREFIX = "fraud:cache"
_HITS_KEY = "fraud:cache:hits"
_MISSES_KEY = "fraud:cache:misses"


def build_cache_key(transaction: dict, user_context: Optional[dict] = None) -> str:
    """Build the AI-response cache key from the transaction's UNIQUE id.

    `user_context` is accepted for backward-compatible call sites but is not part
    of the key (it must not influence cache identity).
    """
    txn_id = transaction.get("id") or transaction.get("transaction_id")
    if not txn_id:
        # No id (shouldn't happen on the hot path): non-reusable key, never collide.
        txn_id = f"noid:{id(transaction)}"
        logger.warning("Transaction missing id; using non-reusable cache key %s", txn_id)
    return f"{_CACHE_PREFIX}:{txn_id}"


async def get(cache_key: str) -> Optional[dict]:
    """Return the cached assessment dict, or None on miss/error (updates hit/miss counters)."""
    r = get_redis()
    try:
        raw = await r.get(cache_key)
        if raw is None:
            await _safe_incr(_MISSES_KEY)
            return None
        await _safe_incr(_HITS_KEY)
        return json.loads(raw)
    except Exception:
        return None  # any cache failure -> treat as a miss


async def set(cache_key: str, assessment_dict: dict, ttl: Optional[int] = None) -> None:
    """Cache an assessment dict under the key, stripping volatile per-call metadata."""
    r = get_redis()
    ttl = ttl if ttl is not None else settings.AI_CACHE_TTL_SECONDS
    try:
        payload = {k: v for k, v in assessment_dict.items() if k not in ("cache_hit", "inference_ms")}
        await r.set(cache_key, json.dumps(payload), ex=ttl)
    except Exception:
        pass  # failing to cache only forfeits a future cost saving


async def _safe_incr(key: str) -> None:
    """Increment a counter, ignoring errors (telemetry must never break flow)."""
    try:
        await get_redis().incr(key)
    except Exception:
        pass


async def get_cache_stats() -> dict:
    """Live cache telemetry for GET /stats: {hits, misses, hit_rate}."""
    r = get_redis()
    try:
        pipe = r.pipeline(transaction=False)
        pipe.get(_HITS_KEY)
        pipe.get(_MISSES_KEY)
        hits_raw, misses_raw = await pipe.execute()
        hits = int(hits_raw or 0)
        misses = int(misses_raw or 0)
        total = hits + misses
        return {"hits": hits, "misses": misses, "hit_rate": (hits / total) if total > 0 else 0.0}
    except Exception:
        return {"hits": 0, "misses": 0, "hit_rate": 0.0}
