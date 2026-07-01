"""Idempotent, code-driven schema migrations applied on startup (no Alembic)."""

import logging

from sqlalchemy import text

from db import engine

logger = logging.getLogger("fraudshield.migrations")

# Each entry is one idempotent DDL/backfill statement, run in order on every boot.
_STATEMENTS: list[str] = [
    # users — login/signup accounts (unique email + unique claimed user_id).
    """
    CREATE TABLE IF NOT EXISTS users (
        id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        email          VARCHAR(255) NOT NULL,
        user_id        VARCHAR(50)  NOT NULL,
        password_hash  TEXT         NOT NULL,
        created_at     TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
        CONSTRAINT uq_users_email   UNIQUE (email),
        CONSTRAINT uq_users_user_id UNIQUE (user_id)
    )
    """,
    # transactions.status (the state machine)
    """
    ALTER TABLE transactions
        ADD COLUMN IF NOT EXISTS status VARCHAR(30) NOT NULL DEFAULT 'SCORING'
    """,
    # CHECK constraint added separately so we can guard against re-adding it.
    """
    DO $$
    BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM pg_constraint WHERE conname = 'transactions_status_check'
        ) THEN
            ALTER TABLE transactions ADD CONSTRAINT transactions_status_check
                CHECK (status IN (
                    'SCORING', 'COMPLETED', 'PENDING_USER_CONFIRMATION',
                    'PENDING_ANALYST_REVIEW', 'DECLINED'
                ));
        END IF;
    END $$;
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_transactions_status
        ON transactions (status, created_at DESC)
    """,
    # Original (pre-conversion) currency + amount the user entered, for display.
    """
    ALTER TABLE transactions
        ADD COLUMN IF NOT EXISTS original_currency VARCHAR(3) DEFAULT 'USD'
    """,
    """
    ALTER TABLE transactions
        ADD COLUMN IF NOT EXISTS original_amount DECIMAL(12, 2)
    """,
    # transaction_audit (transition ledger)
    """
    CREATE TABLE IF NOT EXISTS transaction_audit (
        id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        transaction_id   UUID NOT NULL REFERENCES transactions(id) ON DELETE CASCADE,
        old_state        VARCHAR(30),
        new_state        VARCHAR(30) NOT NULL,
        actor            VARCHAR(10) NOT NULL
                         CHECK (actor IN ('AI', 'USER', 'ANALYST', 'SYSTEM')),
        actor_id         VARCHAR(100),
        reason           TEXT,
        created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_transaction_audit_txn
        ON transaction_audit (transaction_id, created_at)
    """,
    # Backfill: map existing AI recommendations to a starting lifecycle state.
    # Only rows still at default 'SCORING' with a fraud_result are touched (idempotent).
    """
    UPDATE transactions t
    SET status = CASE fr.decision
        WHEN 'APPROVE' THEN 'COMPLETED'
        WHEN 'REVIEW'  THEN 'PENDING_ANALYST_REVIEW'
        WHEN 'DECLINE' THEN 'PENDING_USER_CONFIRMATION'
        ELSE 'SCORING'
    END
    FROM fraud_results fr
    WHERE fr.transaction_id = t.id
      AND t.status = 'SCORING'
    """,
    # Seed an audit record for any transaction that has none yet (historical rows).
    """
    INSERT INTO transaction_audit (transaction_id, old_state, new_state, actor, reason)
    SELECT t.id, NULL, t.status, 'SYSTEM', 'Backfilled from pre-migration data'
    FROM transactions t
    WHERE NOT EXISTS (
        SELECT 1 FROM transaction_audit a WHERE a.transaction_id = t.id
    )
    """,
]


async def apply_migrations() -> None:
    """Run all idempotent migration statements. Safe to call on every startup."""
    async with engine.begin() as conn:
        for stmt in _STATEMENTS:
            await conn.execute(text(stmt))
    logger.info("Schema migrations applied (idempotent).")
