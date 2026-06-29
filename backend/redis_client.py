"""Async Redis helpers for low-latency state (dedup, velocity, context, cache, feedback)."""

import json
from typing import Optional

import redis.asyncio as aioredis

from config import settings

_THIRTY_DAYS = 2_592_000
_SEVEN_DAYS = 604_800

# One client per process; decode_responses=True so we get str back, not bytes.
_redis: Optional[aioredis.Redis] = None


def get_redis() -> aioredis.Redis:
    """Lazily create and return the shared async Redis client."""
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(
            settings.REDIS_URL,
            encoding="utf-8",
            decode_responses=True,
            health_check_interval=30,
        )
    return _redis


async def ping_redis() -> bool:
    """Connectivity probe for GET /health. Never raises."""
    try:
        return bool(await get_redis().ping())
    except Exception:
        return False


async def close_redis() -> None:
    """Close the pool on app shutdown."""
    global _redis
    if _redis is not None:
        await _redis.aclose()
        _redis = None


# --- Deduplication ---
async def is_duplicate(txn_id: str) -> bool:
    """Atomically check-and-mark a txn id in the 24h dedup window (SET NX)."""
    key = f"dedup:{txn_id}"
    try:
        created = await get_redis().set(key, "1", nx=True, ex=settings.DEDUP_TTL_SECONDS)
        return created is None  # None => key existed => duplicate
    except Exception:
        return False  # fail open: don't silently drop transactions


async def claim_fingerprint(fingerprint: str, txn_id: str) -> Optional[str]:
    """SET-NX claim a content fingerprint; returns None if new, else the owning id."""
    key = f"dedup:fp:{fingerprint}"
    try:
        created = await get_redis().set(key, txn_id, nx=True, ex=settings.DEDUP_TTL_SECONDS)
        if created:
            return None
        return await get_redis().get(key)
    except Exception:
        return None  # fail open: treat as new rather than drop


# --- Velocity counters ---
async def increment_velocity(user_id: str) -> tuple[int, int]:
    """Increment the user's 1h + 24h counters (sliding fixed window) and return both."""
    r = get_redis()
    k1h = f"user:txn_count_1h:{user_id}"
    k24h = f"user:txn_count_24h:{user_id}"
    try:
        pipe = r.pipeline(transaction=True)
        pipe.incr(k1h)
        pipe.incr(k24h)
        c1h, c24h = await pipe.execute()

        # Only (re)arm TTL when the window was freshly created this call.
        exp = r.pipeline(transaction=True)
        if c1h == 1:
            exp.expire(k1h, settings.VELOCITY_1H_TTL_SECONDS)
        if c24h == 1:
            exp.expire(k24h, settings.VELOCITY_24H_TTL_SECONDS)
        await exp.execute()
        return int(c1h), int(c24h)
    except Exception:
        return 0, 0


async def get_velocity(user_id: str) -> tuple[int, int]:
    """Read current 1h / 24h counters without incrementing. Missing -> 0."""
    r = get_redis()
    try:
        pipe = r.pipeline(transaction=False)
        pipe.get(f"user:txn_count_1h:{user_id}")
        pipe.get(f"user:txn_count_24h:{user_id}")
        c1h, c24h = await pipe.execute()
        return int(c1h or 0), int(c24h or 0)
    except Exception:
        return 0, 0


# --- Behavioral context: running average amount + usual merchants ---
async def get_user_avg_amount(user_id: str) -> float:
    """User's 30d average transaction amount. Missing -> 0.0."""
    try:
        val = await get_redis().get(f"user:avg_amount:{user_id}")
        return float(val) if val is not None else 0.0
    except Exception:
        return 0.0


async def update_user_avg_amount(user_id: str, amount: float) -> float:
    """Update the exact running mean (Welford's online mean) and return it."""
    r = get_redis()
    mean_key = f"user:avg_amount:{user_id}"
    count_key = f"user:avg_count:{user_id}"
    try:
        cur_mean = await r.get(mean_key)
        cur_count = await r.get(count_key)
        mean = float(cur_mean) if cur_mean is not None else 0.0
        count = int(cur_count) if cur_count is not None else 0

        new_count = count + 1
        new_mean = mean + (amount - mean) / new_count

        pipe = r.pipeline(transaction=True)
        pipe.set(mean_key, new_mean, ex=_THIRTY_DAYS)
        pipe.set(count_key, new_count, ex=_THIRTY_DAYS)
        await pipe.execute()
        return new_mean
    except Exception:
        return amount


async def get_user_merchants(user_id: str) -> list[str]:
    """User's usual merchants (most recent first). Missing -> []."""
    try:
        raw = await get_redis().get(f"user:merchants:{user_id}")
        return json.loads(raw) if raw else []
    except Exception:
        return []


async def add_user_merchant(user_id: str, merchant: str, max_keep: int = 10) -> None:
    """Record a merchant in the user's recent-merchant list (dedup, MRU, capped)."""
    r = get_redis()
    key = f"user:merchants:{user_id}"
    try:
        merchants = await get_user_merchants(user_id)
        merchants = [m for m in merchants if m != merchant]
        merchants.insert(0, merchant)
        merchants = merchants[:max_keep]
        await r.set(key, json.dumps(merchants), ex=_THIRTY_DAYS)
    except Exception:
        pass


# --- Merchant fraud rate ---
async def get_merchant_fraud_rate(merchant: str) -> Optional[float]:
    """Historical fraud rate for a merchant (0.0–1.0), or None if unknown."""
    try:
        val = await get_redis().get(f"merchant:fraud_rate:{merchant}")
        return float(val) if val is not None else None
    except Exception:
        return None


async def set_merchant_fraud_rate(merchant: str, rate: float) -> None:
    """Set/refresh a merchant's known fraud rate (24h TTL)."""
    try:
        await get_redis().set(f"merchant:fraud_rate:{merchant}", rate, ex=settings.DEDUP_TTL_SECONDS)
    except Exception:
        pass


# --- Analyst feedback summary (the no-retraining feedback loop) ---
async def get_feedback_summary(user_id: str) -> Optional[dict]:
    """Structured feedback summary for a user, or None if none recorded yet."""
    try:
        raw = await get_redis().get(f"feedback:{user_id}")
        return json.loads(raw) if raw else None
    except Exception:
        return None


async def record_feedback(user_id: str, label: str, merchant: Optional[str] = None) -> dict:
    """Merge one analyst label into the user's running feedback summary (7d TTL)."""
    r = get_redis()
    key = f"feedback:{user_id}"
    try:
        current = await get_feedback_summary(user_id) or {
            "confirmed_fraud": 0,
            "false_positive": 0,
            "fp_merchants": [],
        }

        if label == "CONFIRMED_FRAUD":
            current["confirmed_fraud"] += 1
        elif label == "FALSE_POSITIVE":
            current["false_positive"] += 1
            if merchant and merchant not in current["fp_merchants"]:
                current["fp_merchants"].append(merchant)

        current["summary"] = _render_feedback_summary(current)
        await r.set(key, json.dumps(current), ex=_SEVEN_DAYS)
        return current
    except Exception:
        return {"confirmed_fraud": 0, "false_positive": 0, "fp_merchants": [], "summary": ""}


def _render_feedback_summary(s: dict) -> str:
    """Turn the counters into the one-paragraph context string for prompts."""
    parts: list[str] = []
    cf = s.get("confirmed_fraud", 0)
    fp = s.get("false_positive", 0)
    if cf:
        parts.append(
            f"Analyst previously confirmed {cf} fraud case{'s' if cf != 1 else ''} for this user."
        )
    if fp:
        merchants = s.get("fp_merchants", [])
        tail = f" (merchant{'s' if len(merchants) != 1 else ''}: {', '.join(merchants)})" if merchants else ""
        parts.append(f"{fp} false positive{'s' if fp != 1 else ''} recorded{tail}.")
    return " ".join(parts)


# --- Aggregate context: one call the consumer uses to build the prompt ---
async def build_user_context(user_id: str) -> dict:
    """Assemble the full behavioral context dict the prompt builder expects."""
    c1h, c24h = await get_velocity(user_id)
    avg_amount = await get_user_avg_amount(user_id)
    merchants = await get_user_merchants(user_id)
    feedback = await get_feedback_summary(user_id)
    return {
        "txn_count_1h": c1h,
        "txn_count_24h": c24h,
        "avg_amount": avg_amount,
        "top_merchants": merchants,
        "feedback": feedback,
    }
