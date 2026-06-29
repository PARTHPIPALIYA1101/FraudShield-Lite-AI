"""FastAPI application: app wiring, lifespan, and all routes."""

import asyncio
import logging
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from config import settings
from db import dispose_engine, ping_db
from models import (
    ChatRequest,
    FeedbackCreate,
    FeedbackResponse,
    HealthOut,
    PaginatedTransactions,
    StateActionRequest,
    StateActionResponse,
    StatsOut,
    TransactionCreate,
    TransactionQueued,
    TransactionWithResult,
)
from redis_client import close_redis, ping_redis
from transaction_state import (
    Actor,
    InvalidTransition,
    TransactionNotFound,
    TransactionStatus,
    apply_transition,
    transaction_event,
)
from websocket_manager import manager

# Surface our own "fraudshield.*" loggers alongside uvicorn's.
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("fraudshield.api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: migrate -> create topics -> launch consumer. Shutdown: stop everything cleanly."""
    from kafka_producer import close as close_producer, ensure_topics
    from kafka_consumer import consume_loop
    from ai.scorer_factory import close_scorer
    from migrations import apply_migrations

    await apply_migrations()         # idempotent schema migration before anything reads
    ensure_topics()

    stop_event = asyncio.Event()
    consumer_task = asyncio.create_task(consume_loop(stop_event))
    app.state.consumer_stop = stop_event
    app.state.consumer_task = consumer_task
    logger.info("Startup complete: topics ensured, consumer running.")

    yield

    stop_event.set()
    try:
        await asyncio.wait_for(consumer_task, timeout=15)
    except asyncio.TimeoutError:
        logger.warning("Consumer did not stop in time; cancelling.")
        consumer_task.cancel()

    close_producer()
    await close_scorer()
    await dispose_engine()
    await close_redis()


app = FastAPI(
    title="FraudShield Lite AI",
    description="Real-time fraud detection with an LLM as the scoring engine.",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS so the Next.js dev frontend (localhost:3000) can call the API + WS.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- Health: live-probes each dependency; never raises ---
async def _ping_kafka() -> bool:
    """Cheap Kafka liveness check via AdminClient metadata (run off-loop; failure -> False)."""
    import asyncio

    def _probe() -> bool:
        try:
            from confluent_kafka.admin import AdminClient

            admin = AdminClient({"bootstrap.servers": settings.KAFKA_BOOTSTRAP_SERVERS})
            return admin.list_topics(timeout=3.0) is not None
        except Exception:
            return False

    try:
        return await asyncio.to_thread(_probe)
    except Exception:
        return False


def _anthropic_configured() -> bool:
    """True if a real API key is present (config-presence check, no billed call)."""
    key = settings.ANTHROPIC_API_KEY or ""
    return bool(key) and key != "your_api_key_here"


@app.get("/health", response_model=HealthOut, tags=["system"])
async def health() -> HealthOut:
    """Per-dependency health. status='ok' only if every dependency is healthy."""
    db_ok = await ping_db()
    redis_ok = await ping_redis()
    kafka_ok = await _ping_kafka()
    anthropic_ok = _anthropic_configured()

    all_ok = db_ok and redis_ok and kafka_ok and anthropic_ok
    return HealthOut(
        status="ok" if all_ok else "degraded",
        kafka=kafka_ok,
        db=db_ok,
        redis=redis_ok,
        anthropic_api=anthropic_ok,
    )


# --- Transactions ---
@app.post(
    "/transactions",
    response_model=TransactionQueued,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["transactions"],
)
async def create_transaction(body: TransactionCreate) -> TransactionQueued:
    """Ingest a transaction: persist (status=SCORING) -> publish to Kafka -> 202.

    Each POST is a DISTINCT financial event with its own id and a fresh AI
    evaluation; we do NOT dedup on content. Idempotency is at the transaction_id
    level (a Kafka redelivery hits the AI cache + UPSERTs the same row).
    """
    from sqlalchemy import text

    from db import session_scope
    from kafka_producer import publish_raw

    txn_id = str(uuid4())  # unique per POST -> every submission scored fresh
    logger.info(
        "Ingest txn=%s user=%s merchant=%s amount=%s (new financial event)",
        txn_id, body.user_id, body.merchant, body.amount,
    )

    # Persist the raw row + seed the audit ledger with the ingest event.
    insert_sql = text(
        """
        INSERT INTO transactions
            (id, user_id, merchant, amount, is_foreign_merchant, location, status)
        VALUES
            (:id, :user_id, :merchant, :amount, :is_foreign_merchant, :location, 'SCORING')
        RETURNING "timestamp"
        """
    )
    audit_sql = text(
        "INSERT INTO transaction_audit "
        "(transaction_id, old_state, new_state, actor, reason) "
        "VALUES (:id, NULL, 'SCORING', 'SYSTEM', 'Transaction ingested')"
    )
    try:
        async with session_scope() as session:
            result = await session.execute(
                insert_sql,
                {
                    "id": txn_id,
                    "user_id": body.user_id,
                    "merchant": body.merchant,
                    "amount": body.amount,
                    "is_foreign_merchant": body.is_foreign_merchant,
                    "location": body.location,
                },
            )
            ts = result.scalar_one()
            await session.execute(audit_sql, {"id": txn_id})
    except Exception as exc:
        logger.exception("Failed to persist transaction: %s", exc)
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail="Could not persist transaction.")

    # Publish to transactions.raw for the consumer to score (keyed by user_id).
    message = {
        "id": txn_id,
        "user_id": body.user_id,
        "merchant": body.merchant,
        "amount": body.amount,
        "is_foreign_merchant": body.is_foreign_merchant,
        "location": body.location,
        "timestamp": ts.isoformat(),
    }
    try:
        publish_raw(message)
    except Exception as exc:
        logger.exception("Failed to publish transaction to Kafka: %s", exc)
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail="Could not queue transaction.")

    return TransactionQueued(transaction_id=txn_id, status="queued")


# Combined transaction + fraud_result select, assembled in-query (no N+1).
_TXN_SELECT = """
SELECT
    t.id, t.user_id, t.merchant, t.amount, t.is_foreign_merchant,
    t.location, t.status, t."timestamp", t.created_at,
    fr.id            AS fr_id,
    fr.fraud_score   AS fr_fraud_score,
    fr.decision      AS fr_decision,
    fr.confidence    AS fr_confidence,
    fr.risk_factors  AS fr_risk_factors,
    fr.patterns_matched AS fr_patterns_matched,
    fr.explanation   AS fr_explanation,
    fr.ai_model_used AS fr_ai_model_used,
    fr.cache_hit     AS fr_cache_hit,
    fr.inference_ms  AS fr_inference_ms,
    fr.created_at    AS fr_created_at
FROM transactions t
LEFT JOIN fraud_results fr ON fr.transaction_id = t.id
"""


def _row_to_txn_with_result(row) -> TransactionWithResult:
    """Map a joined transactions+fraud_results row onto the response schema."""
    from models import FraudResultOut, TransactionOut

    m = row._mapping
    txn = TransactionOut(
        id=m["id"],
        user_id=m["user_id"],
        merchant=m["merchant"],
        amount=float(m["amount"]),
        is_foreign_merchant=m["is_foreign_merchant"],
        location=m["location"],
        status=m["status"],
        timestamp=m["timestamp"],
        created_at=m["created_at"],
    )
    fraud_result = None
    if m["fr_id"] is not None:
        fraud_result = FraudResultOut(
            id=m["fr_id"],
            transaction_id=m["id"],
            fraud_score=float(m["fr_fraud_score"]),
            decision=m["fr_decision"],
            confidence=m["fr_confidence"],
            risk_factors=m["fr_risk_factors"],
            patterns_matched=m["fr_patterns_matched"],
            explanation=m["fr_explanation"],
            ai_model_used=m["fr_ai_model_used"],
            cache_hit=m["fr_cache_hit"],
            inference_ms=m["fr_inference_ms"],
            created_at=m["fr_created_at"],
        )
    return TransactionWithResult(transaction=txn, fraud_result=fraud_result)


@app.get("/transactions", response_model=PaginatedTransactions, tags=["transactions"])
async def list_transactions(
    page: int = 1,
    limit: int = 20,
    status: str | None = None,
    decision: str | None = None,
) -> PaginatedTransactions:
    """Paginated transactions + results, newest first; filter by lifecycle status and/or AI decision."""
    from sqlalchemy import text

    from db import session_scope

    page = max(1, page)
    limit = max(1, min(limit, 100))
    offset = (page - 1) * limit

    clauses: list[str] = []
    params: dict = {"limit": limit, "offset": offset}
    filter_params: dict = {}
    if status:
        clauses.append("t.status = :status")
        filter_params["status"] = status.upper()
    if decision:
        clauses.append("fr.decision = :decision")
        filter_params["decision"] = decision.upper()
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    params.update(filter_params)

    list_sql = text(_TXN_SELECT + where + ' ORDER BY t.created_at DESC LIMIT :limit OFFSET :offset')
    count_sql = text(
        "SELECT COUNT(*) FROM transactions t "
        "LEFT JOIN fraud_results fr ON fr.transaction_id = t.id" + where
    )

    async with session_scope() as session:
        rows = (await session.execute(list_sql, params)).fetchall()
        total = (await session.execute(count_sql, filter_params)).scalar_one()

    items = [_row_to_txn_with_result(r) for r in rows]
    return PaginatedTransactions(items=items, total=total, page=page, limit=limit)


@app.get("/transactions/{transaction_id}", response_model=TransactionWithResult, tags=["transactions"])
async def get_transaction(transaction_id: str) -> TransactionWithResult:
    """Full transaction + fraud_result + feedback + audit timeline for one id."""
    from sqlalchemy import text

    from db import session_scope
    from models import AuditEntry, FeedbackOut

    async with session_scope() as session:
        row = (
            await session.execute(text(_TXN_SELECT + " WHERE t.id = :id"), {"id": transaction_id})
        ).fetchone()
        if row is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Transaction not found.")

        fb_rows = (
            await session.execute(
                text(
                    "SELECT id, transaction_id, fraud_result_id, analyst_label, "
                    "analyst_notes, created_at FROM analyst_feedback "
                    "WHERE transaction_id = :id ORDER BY created_at DESC"
                ),
                {"id": transaction_id},
            )
        ).fetchall()

        audit_rows = (
            await session.execute(
                text(
                    "SELECT id, transaction_id, old_state, new_state, actor, "
                    "actor_id, reason, created_at FROM transaction_audit "
                    "WHERE transaction_id = :id ORDER BY created_at ASC"
                ),
                {"id": transaction_id},
            )
        ).fetchall()

    out = _row_to_txn_with_result(row)
    out.feedback = [
        FeedbackOut(
            id=r._mapping["id"],
            transaction_id=r._mapping["transaction_id"],
            fraud_result_id=r._mapping["fraud_result_id"],
            analyst_label=r._mapping["analyst_label"],
            analyst_notes=r._mapping["analyst_notes"],
            created_at=r._mapping["created_at"],
        )
        for r in fb_rows
    ]
    out.audit = [AuditEntry.model_validate(r._mapping) for r in audit_rows]
    return out


# --- State actions: the human decisions the AI may only RECOMMEND ---
async def _run_state_action(
    transaction_id: str,
    new_status: str,
    actor: str,
    default_reason: str,
    body: StateActionRequest | None,
) -> StateActionResponse:
    """Shared driver for confirm/cancel/approve/reject (guarded transition + broadcast)."""
    from sqlalchemy import text

    from db import session_scope

    reason = (body.reason if body and body.reason else default_reason)
    actor_id = body.actor_id if body else None

    try:
        async with session_scope() as session:
            old_status, updated = await apply_transition(
                session, transaction_id, new_status, actor, reason, actor_id
            )
            fr_row = (
                await session.execute(
                    text(
                        "SELECT fraud_score, decision, confidence, risk_factors, "
                        "patterns_matched, explanation, ai_model_used, cache_hit, "
                        "inference_ms FROM fraud_results WHERE transaction_id = :id"
                    ),
                    {"id": transaction_id},
                )
            ).fetchone()
    except TransactionNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Transaction not found.")
    except InvalidTransition as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail=f"Transaction is in state {exc.current!r}; this action is not allowed.",
        )

    fraud_result = None
    recommendation = None
    if fr_row is not None:
        fraud_result = dict(fr_row._mapping)
        fraud_result["fraud_score"] = float(fraud_result["fraud_score"])
        recommendation = fraud_result["decision"]

    transition = {"old_state": old_status, "new_state": new_status, "actor": actor, "reason": reason}
    # Broadcast AFTER the commit so dashboards never see uncommitted state.
    await manager.broadcast(transaction_event(updated, fraud_result, new_status, transition))

    return StateActionResponse(
        transaction_id=transaction_id,
        transaction_status=new_status,
        ai_recommendation=recommendation,
    )


@app.post("/transactions/{transaction_id}/confirm", response_model=StateActionResponse, tags=["state-actions"])
async def confirm_transaction(transaction_id: str, body: StateActionRequest | None = None) -> StateActionResponse:
    """USER 'Continue Anyway': PENDING_USER_CONFIRMATION -> PENDING_ANALYST_REVIEW (not completed)."""
    return await _run_state_action(
        transaction_id, TransactionStatus.PENDING_ANALYST_REVIEW, Actor.USER, "User accepted fraud risk", body,
    )


@app.post("/transactions/{transaction_id}/cancel", response_model=StateActionResponse, tags=["state-actions"])
async def cancel_transaction(transaction_id: str, body: StateActionRequest | None = None) -> StateActionResponse:
    """USER 'Cancel Transaction': PENDING_USER_CONFIRMATION -> DECLINED."""
    return await _run_state_action(
        transaction_id, TransactionStatus.DECLINED, Actor.USER, "Cancelled by User", body,
    )


@app.post("/transactions/{transaction_id}/approve", response_model=StateActionResponse, tags=["state-actions"])
async def approve_transaction(transaction_id: str, body: StateActionRequest | None = None) -> StateActionResponse:
    """ANALYST approve: PENDING_ANALYST_REVIEW -> COMPLETED."""
    return await _run_state_action(
        transaction_id, TransactionStatus.COMPLETED, Actor.ANALYST, "Approved by analyst", body,
    )


@app.post("/transactions/{transaction_id}/reject", response_model=StateActionResponse, tags=["state-actions"])
async def reject_transaction(transaction_id: str, body: StateActionRequest | None = None) -> StateActionResponse:
    """ANALYST reject: PENDING_ANALYST_REVIEW -> DECLINED."""
    return await _run_state_action(
        transaction_id, TransactionStatus.DECLINED, Actor.ANALYST, "Rejected by analyst", body,
    )


# --- Stats: dashboard KPIs (status aggregates + live Redis cache telemetry) ---
@app.get("/stats", response_model=StatsOut, tags=["stats"])
async def stats() -> StatsOut:
    """Today's KPIs keyed off transaction lifecycle status, plus the live cache hit-rate."""
    from sqlalchemy import text

    from db import session_scope
    from ai.cache_manager import get_cache_stats

    agg_sql = text(
        """
        SELECT
            COUNT(*) AS total_today,
            COUNT(*) FILTER (WHERE t.status = 'PENDING_USER_CONFIRMATION') AS pending_confirmation,
            COUNT(*) FILTER (WHERE t.status = 'PENDING_ANALYST_REVIEW')    AS pending_review,
            COUNT(*) FILTER (WHERE t.status = 'COMPLETED')                 AS completed_today,
            COUNT(*) FILTER (WHERE t.status = 'DECLINED')                  AS declined_today,
            COALESCE(AVG(fr.fraud_score), 0)  AS avg_fraud_score,
            COALESCE(AVG(fr.inference_ms), 0) AS avg_inference_ms
        FROM transactions t
        LEFT JOIN fraud_results fr ON fr.transaction_id = t.id
        WHERE t.created_at >= date_trunc('day', NOW())
        """
    )
    async with session_scope() as session:
        m = (await session.execute(agg_sql)).fetchone()._mapping

    total_today = int(m["total_today"])
    pending_confirmation = int(m["pending_confirmation"])
    pending_review = int(m["pending_review"])
    completed_today = int(m["completed_today"])
    declined_today = int(m["declined_today"])
    flagged_count = pending_confirmation + pending_review
    not_auto_approved = flagged_count + declined_today  # share NOT auto-approved
    fraud_rate = (not_auto_approved / total_today) if total_today else 0.0

    cache = await get_cache_stats()

    return StatsOut(
        total_today=total_today,
        pending_confirmation=pending_confirmation,
        pending_review=pending_review,
        completed_today=completed_today,
        declined_today=declined_today,
        flagged_count=flagged_count,
        fraud_rate=round(fraud_rate, 4),
        avg_fraud_score=round(float(m["avg_fraud_score"]), 4),
        cache_hit_rate=round(float(cache["hit_rate"]), 4),
        avg_inference_ms=round(float(m["avg_inference_ms"]), 1),
    )


# --- Feedback: the no-retraining human-in-the-loop loop ---
@app.post("/feedback", response_model=FeedbackResponse, tags=["feedback"])
async def feedback(body: FeedbackCreate) -> FeedbackResponse:
    """Persist an analyst label + fold it into the user's Redis summary for future prompts."""
    from sqlalchemy import text

    from db import session_scope
    from redis_client import record_feedback

    txn_id = str(body.transaction_id)

    async with session_scope() as session:
        # Fetch the txn (user_id + merchant) and its fraud_result id in one go.
        row = (
            await session.execute(
                text(
                    "SELECT t.user_id, t.merchant, fr.id AS fraud_result_id "
                    "FROM transactions t "
                    "LEFT JOIN fraud_results fr ON fr.transaction_id = t.id "
                    "WHERE t.id = :id"
                ),
                {"id": txn_id},
            )
        ).fetchone()

        if row is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Transaction not found.")
        if row._mapping["fraud_result_id"] is None:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail="Transaction not scored yet — try again once it has a result.",
            )

        user_id = row._mapping["user_id"]
        merchant = row._mapping["merchant"]
        fraud_result_id = row._mapping["fraud_result_id"]

        await session.execute(
            text(
                "INSERT INTO analyst_feedback "
                "(transaction_id, fraud_result_id, analyst_label, analyst_notes) "
                "VALUES (:txn_id, :fr_id, :label, :notes)"
            ),
            {"txn_id": txn_id, "fr_id": fraud_result_id, "label": body.label.value, "notes": body.notes},
        )

    # Outside the DB transaction: a Redis hiccup must not roll back the audit row.
    await record_feedback(user_id, body.label.value, merchant)

    return FeedbackResponse(success=True)


# --- Chat: streaming AI-analyst assistant (provider-agnostic via ai/chat.py) ---
async def _load_chat_history(session_id: str) -> list[dict]:
    """Load a session's prior turns ([] if new)."""
    from sqlalchemy import text

    from db import session_scope

    async with session_scope() as session:
        row = (
            await session.execute(
                text("SELECT messages FROM ai_chat_sessions WHERE session_id = :sid"),
                {"sid": session_id},
            )
        ).fetchone()
    if row is None:
        return []
    msgs = row._mapping["messages"]
    return msgs if isinstance(msgs, list) else []


async def _load_context_transactions(txn_ids: list) -> list[dict]:
    """Fetch the analyst-pinned transactions + their results for the context block."""
    if not txn_ids:
        return []
    from sqlalchemy import text

    from db import session_scope

    ids = [str(t) for t in txn_ids]
    async with session_scope() as session:
        rows = (
            await session.execute(text(_TXN_SELECT + " WHERE t.id = ANY(:ids)"), {"ids": ids})
        ).fetchall()

    out: list[dict] = []
    for r in rows:
        m = r._mapping
        out.append(
            {
                "user_id": m["user_id"],
                "merchant": m["merchant"],
                "amount": float(m["amount"]),
                "is_foreign_merchant": m["is_foreign_merchant"],
                "decision": m["fr_decision"],
                "fraud_score": float(m["fr_fraud_score"]) if m["fr_fraud_score"] is not None else None,
                "explanation": m["fr_explanation"],
            }
        )
    return out


async def _save_chat_session(session_id: str, messages: list[dict]) -> None:
    """UPSERT the full message history for a session (updated_at trigger fires)."""
    import json as _json

    from sqlalchemy import text

    from db import session_scope

    async with session_scope() as session:
        await session.execute(
            text(
                "INSERT INTO ai_chat_sessions (session_id, messages) "
                "VALUES (:sid, CAST(:msgs AS JSONB)) "
                "ON CONFLICT (session_id) DO UPDATE SET messages = EXCLUDED.messages"
            ),
            {"sid": session_id, "msgs": _json.dumps(messages)},
        )


@app.post("/chat", tags=["chat"])
async def chat(body: ChatRequest):
    """Stream the AI analyst's answer token-by-token; persist the session after it completes."""
    from ai.chat import build_context_block, stream_answer

    history = await _load_chat_history(body.session_id)
    context_txns = await _load_context_transactions(body.context_txn_ids)
    context_block = build_context_block(context_txns)
    user_message = f"{context_block}{body.message}"

    async def generate():
        chunks: list[str] = []
        try:
            async for piece in stream_answer(history, user_message):
                chunks.append(piece)
                yield piece
        except Exception as exc:  # noqa: BLE001 — surface a clean error to the client
            logger.exception("Chat streaming failed: %s", exc)
            yield "\n[error: the assistant is temporarily unavailable]"
            return

        # Store the analyst's RAW message (without the injected context block).
        answer = "".join(chunks)
        new_history = history + [
            {"role": "user", "content": body.message},
            {"role": "assistant", "content": answer},
        ]
        try:
            await _save_chat_session(body.session_id, new_history)
        except Exception as exc:  # noqa: BLE001 — persistence failure is non-fatal
            logger.warning("Failed to persist chat session %s: %s", body.session_id, exc)

    return StreamingResponse(generate(), media_type="text/plain; charset=utf-8")


# --- WebSocket: live feed; the consumer + state actions broadcast here ---
@app.websocket("/ws/alerts")
async def ws_alerts(websocket: WebSocket) -> None:
    """Keep the connection open (server-push channel); prune the client on disconnect."""
    from websocket_manager import manager

    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()  # park until the client disconnects
    except WebSocketDisconnect:
        await manager.disconnect(websocket)
    except Exception:
        await manager.disconnect(websocket)


@app.get("/", tags=["system"])
async def root() -> dict:
    """Tiny convenience so hitting the base URL isn't a 404."""
    return {
        "service": "FraudShield Lite AI",
        "version": app.version,
        "docs": "/docs",
        "health": "/health",
    }
