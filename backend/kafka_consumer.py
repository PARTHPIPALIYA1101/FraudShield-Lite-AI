"""The scoring worker: poll transactions.raw -> context -> score -> persist -> status -> broadcast."""

import asyncio
import json
import logging
from typing import Optional

from confluent_kafka import Consumer, KafkaError

from config import settings
from db import session_scope
from kafka_producer import publish_scored
from models import KafkaTransactionMessage
from redis_client import (
    add_user_merchant,
    build_user_context,
    get_merchant_fraud_rate,
    increment_velocity,
    update_user_avg_amount,
)
from policy import apply_policies
from websocket_manager import manager
from ai.scorer_factory import get_scorer
from ai.base import ScoringError, api_failure_assessment
from transaction_state import (
    Actor,
    InvalidTransition,
    RECOMMENDATION_TO_STATUS,
    TransactionNotFound,
    TransactionStatus,
    apply_transition,
    transaction_event,
)

logger = logging.getLogger("fraudshield.consumer")


def _build_consumer() -> Consumer:
    """Build the group consumer (manual commits + earliest reset to process the backlog)."""
    return Consumer(
        {
            "bootstrap.servers": settings.KAFKA_BOOTSTRAP_SERVERS,
            "group.id": settings.KAFKA_CONSUMER_GROUP,
            "auto.offset.reset": "earliest",
            "enable.auto.commit": False,
            "client.id": "fraudshield-consumer",
        }
    )


# Idempotent UPSERT into fraud_results (one assessment per transaction_id).
_UPSERT_FRAUD_RESULT = """
INSERT INTO fraud_results (
    transaction_id, fraud_score, decision, confidence,
    risk_factors, patterns_matched, explanation,
    ai_model_used, cache_hit, inference_ms
) VALUES (
    :transaction_id, :fraud_score, :decision, :confidence,
    CAST(:risk_factors AS JSONB), CAST(:patterns_matched AS JSONB), :explanation,
    :ai_model_used, :cache_hit, :inference_ms
)
ON CONFLICT (transaction_id) DO UPDATE SET
    fraud_score      = EXCLUDED.fraud_score,
    decision         = EXCLUDED.decision,
    confidence       = EXCLUDED.confidence,
    risk_factors     = EXCLUDED.risk_factors,
    patterns_matched = EXCLUDED.patterns_matched,
    explanation      = EXCLUDED.explanation,
    ai_model_used    = EXCLUDED.ai_model_used,
    cache_hit        = EXCLUDED.cache_hit,
    inference_ms     = EXCLUDED.inference_ms
"""


async def _persist_assessment(transaction_id: str, assessment) -> None:
    """UPSERT the assessment so a Kafka redelivery overwrites rather than dupes."""
    from sqlalchemy import text

    data = assessment.model_dump()
    params = {
        "transaction_id": transaction_id,
        "fraud_score": data["fraud_score"],
        "decision": data["decision"],
        "confidence": data["confidence"],
        "risk_factors": json.dumps(data["risk_factors"]),       # JSONB: bind as text, cast in SQL
        "patterns_matched": json.dumps(data["patterns_matched"]),
        "explanation": data["explanation"],
        "ai_model_used": data["ai_model_used"],
        "cache_hit": data["cache_hit"],
        "inference_ms": data["inference_ms"],
    }
    async with session_scope() as session:
        await session.execute(text(_UPSERT_FRAUD_RESULT), params)


async def _process_message(raw_value: bytes) -> None:
    """Score one raw transaction end to end. Never raises on an LLM failure."""
    msg = KafkaTransactionMessage.model_validate_json(raw_value)
    txn = msg.model_dump()
    user_id = msg.user_id

    # 1. Behavioral context (the user's pattern BEFORE this txn).
    user_context = await build_user_context(user_id)
    feedback = user_context.get("feedback") or {}
    feedback_context: Optional[str] = feedback.get("summary") or None

    is_first_visit = msg.merchant not in (user_context.get("top_merchants") or [])
    merchant_context = {
        "fraud_rate": await get_merchant_fraud_rate(msg.merchant),
        "is_first_visit": is_first_visit,
    }

    # 2. Score (cache-aware; safe fallback on unrecoverable failure — never drop a txn).
    scorer = get_scorer()
    try:
        assessment = await scorer.score_transaction(txn, user_context, merchant_context, feedback_context)
    except ScoringError as exc:
        logger.error("Scoring failed for txn %s, persisting fallback: %s", msg.id, exc)
        assessment = api_failure_assessment(str(exc))

    # Enforce hard business rules on top of the AI score (e.g. new-user limit).
    assessment = apply_policies(assessment, txn, user_context)

    # 3. Persist the assessment (idempotent UPSERT).
    await _persist_assessment(msg.id, assessment)

    # 4. Fold this txn into the user's baseline for the NEXT one.
    await increment_velocity(user_id)
    await update_user_avg_amount(user_id, msg.amount)
    await add_user_merchant(user_id, msg.merchant)

    # 5. Advance SCORING -> recommendation status (a RECOMMENDATION, not the final
    #    decision). Guarded to {SCORING}: a redelivery where the txn already advanced
    #    raises InvalidTransition and keeps the current state — idempotent.
    decision = assessment.model_dump()["decision"]
    new_status = RECOMMENDATION_TO_STATUS.get(decision, TransactionStatus.PENDING_ANALYST_REVIEW)
    current_status = new_status
    transition = None
    try:
        async with session_scope() as session:
            old_status, _ = await apply_transition(
                session,
                msg.id,
                new_status,
                actor=Actor.AI,
                reason=f"AI recommendation: {decision}",
                expected_from={TransactionStatus.SCORING},
            )
        transition = {
            "old_state": old_status,
            "new_state": new_status,
            "actor": Actor.AI,
            "reason": f"AI recommendation: {decision}",
        }
    except InvalidTransition as exc:
        current_status = exc.current or new_status
        logger.info("Skipping AI transition for txn %s — already at %s", msg.id, current_status)
    except TransactionNotFound:
        logger.warning("Transaction %s vanished before state transition", msg.id)
        current_status = new_status

    # 6. Fan out: scored topic + live status update to every dashboard (every txn).
    fraud_result = assessment.model_dump()
    try:
        publish_scored({"user_id": user_id, "transaction": txn, "fraud_result": fraud_result})
    except Exception as exc:  # noqa: BLE001 — republish is best-effort
        logger.warning("Failed to republish scored txn %s: %s", msg.id, exc)

    await manager.broadcast(transaction_event(txn, fraud_result, current_status, transition))

    logger.info(
        "Scored txn %s: %s -> %s (score=%.2f, cache_hit=%s, %dms)",
        msg.id, decision, current_status, assessment.fraud_score,
        assessment.cache_hit, assessment.inference_ms,
    )


async def consume_loop(stop_event: asyncio.Event) -> None:
    """Poll transactions.raw until stopped; commit only after each message is processed."""
    consumer = _build_consumer()
    consumer.subscribe([settings.KAFKA_TOPIC_RAW])
    logger.info("Consumer subscribed to %s (group=%s)", settings.KAFKA_TOPIC_RAW, settings.KAFKA_CONSUMER_GROUP)

    try:
        while not stop_event.is_set():
            # Short timeout so the loop stays responsive to stop_event. poll() is
            # blocking C code -> run it off the event loop via to_thread.
            msg = await asyncio.to_thread(consumer.poll, 1.0)
            if msg is None:
                continue
            if msg.error():
                if msg.error().code() != KafkaError._PARTITION_EOF:
                    logger.error("Consumer error: %s", msg.error())
                continue

            try:
                await _process_message(msg.value())
            except Exception as exc:  # noqa: BLE001 — never wedge the loop on a poison message
                logger.exception("Unhandled error processing message: %s", exc)

            # Commit after processing (at-least-once; UPSERT makes reprocessing safe).
            consumer.commit(message=msg, asynchronous=True)
    finally:
        await asyncio.to_thread(consumer.close)
        logger.info("Consumer closed.")
