"""The transaction lifecycle state machine — transition rules, guards, audit, WS payload."""

import logging
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger("fraudshield.state")


class TransactionStatus:
    SCORING = "SCORING"
    COMPLETED = "COMPLETED"
    PENDING_USER_CONFIRMATION = "PENDING_USER_CONFIRMATION"
    PENDING_ANALYST_REVIEW = "PENDING_ANALYST_REVIEW"
    DECLINED = "DECLINED"


class Actor:
    AI = "AI"
    USER = "USER"
    ANALYST = "ANALYST"
    SYSTEM = "SYSTEM"


# AI recommendation -> the lifecycle state it routes into. DECLINE never -> DECLINED.
RECOMMENDATION_TO_STATUS: dict[str, str] = {
    "APPROVE": TransactionStatus.COMPLETED,
    "REVIEW": TransactionStatus.PENDING_ANALYST_REVIEW,
    "DECLINE": TransactionStatus.PENDING_USER_CONFIRMATION,
}

# Allowed transitions out of each state (terminal states map to empty sets).
ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    TransactionStatus.SCORING: {
        TransactionStatus.COMPLETED,
        TransactionStatus.PENDING_ANALYST_REVIEW,
        TransactionStatus.PENDING_USER_CONFIRMATION,
    },
    TransactionStatus.PENDING_USER_CONFIRMATION: {
        TransactionStatus.PENDING_ANALYST_REVIEW,  # user: Continue Anyway
        TransactionStatus.DECLINED,                # user: Cancel
    },
    TransactionStatus.PENDING_ANALYST_REVIEW: {
        TransactionStatus.COMPLETED,  # analyst: Approve
        TransactionStatus.DECLINED,   # analyst: Reject
    },
    TransactionStatus.COMPLETED: set(),
    TransactionStatus.DECLINED: set(),
}


class InvalidTransition(Exception):
    """The requested transition is not legal from the transaction's current state."""

    def __init__(self, current: Optional[str], target: str):
        self.current = current
        self.target = target
        super().__init__(f"Cannot move transaction from {current!r} to {target!r}.")


class TransactionNotFound(Exception):
    """No transaction exists for the given id."""


async def apply_transition(
    session: AsyncSession,
    transaction_id: str,
    new_status: str,
    actor: str,
    reason: Optional[str] = None,
    actor_id: Optional[str] = None,
    *,
    expected_from: Optional[set[str]] = None,
) -> tuple[str, dict]:
    """Atomically (SELECT FOR UPDATE) transition a txn + write an audit row.

    Returns (old_status, txn_dict). Raises TransactionNotFound / InvalidTransition.
    `expected_from` lets a caller constrain the legal source states (e.g. {SCORING}).
    """
    # Lock the row so a concurrent action can't race the state check.
    row = (
        await session.execute(
            text(
                'SELECT id, user_id, merchant, amount, is_foreign_merchant, '
                'location, status, "timestamp", created_at '
                "FROM transactions WHERE id = :id FOR UPDATE"
            ),
            {"id": transaction_id},
        )
    ).fetchone()

    if row is None:
        raise TransactionNotFound(transaction_id)

    current = row._mapping["status"]
    if expected_from is not None and current not in expected_from:
        raise InvalidTransition(current, new_status)
    if new_status not in ALLOWED_TRANSITIONS.get(current, set()):
        raise InvalidTransition(current, new_status)

    await session.execute(
        text("UPDATE transactions SET status = :new WHERE id = :id"),
        {"new": new_status, "id": transaction_id},
    )
    await session.execute(
        text(
            "INSERT INTO transaction_audit "
            "(transaction_id, old_state, new_state, actor, actor_id, reason) "
            "VALUES (:tid, :old, :new, :actor, :actor_id, :reason)"
        ),
        {
            "tid": transaction_id,
            "old": current,
            "new": new_status,
            "actor": actor,
            "actor_id": actor_id,
            "reason": reason,
        },
    )

    # Normalize types so the dict is JSON-serializable for the WS broadcast.
    updated = dict(row._mapping)
    updated["status"] = new_status
    updated["id"] = str(updated["id"])
    updated["amount"] = float(updated["amount"])
    for key in ("timestamp", "created_at"):
        val = updated.get(key)
        if val is not None and hasattr(val, "isoformat"):
            updated[key] = val.isoformat()
    logger.info(
        "Transition %s: %s -> %s by %s%s",
        transaction_id, current, new_status, actor,
        f" ({reason})" if reason else "",
    )
    return current, updated


def transaction_event(
    transaction: dict,
    fraud_result: Optional[dict],
    status: str,
    transition: Optional[dict] = None,
) -> dict:
    """Build the canonical WebSocket payload for a transaction state change."""
    txn = {**transaction, "status": status}
    return {
        "type": "transaction",
        "transaction": txn,
        "fraud_result": fraud_result,
        "status": status,
        "transition": transition,
    }
