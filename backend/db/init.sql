-- ============================================================================
-- FraudShield Lite AI — Database Schema
-- ----------------------------------------------------------------------------
-- Auto-executed by the Postgres container on first boot via the
-- /docker-entrypoint-initdb.d hook (mounted in docker-compose.yml).
--
-- Tables:
--   transactions       : raw events + lifecycle STATUS (the state machine)
--   fraud_results      : the AI's assessment/recommendation per txn (1:1 with txn)
--   analyst_feedback   : human labels that feed the no-retraining feedback loop
--   transaction_audit  : append-only ledger of every status transition (who/why)
--   ai_chat_sessions   : persisted analyst <-> AI chat threads
--
-- Design notes (interview-defensible):
--   * fraud_results.transaction_id is UNIQUE -> enforces exactly one assessment
--     per transaction at the DB layer, which lets the consumer do an idempotent
--     UPSERT (ON CONFLICT) safely on Kafka redelivery.
--   * risk_factors / patterns_matched are JSONB, not separate tables: the shape
--     is owned by Claude's output contract and is read as a whole blob by the
--     UI. Normalizing it would add joins with zero query benefit here.
--   * Money is DECIMAL, never float — no binary rounding error on amounts.
--   * Indexes target the two hot read paths: per-user history (velocity/context
--     lookups) and the dashboard's reverse-chronological feed.
-- ============================================================================

-- gen_random_uuid() is core since PG13; pgcrypto is a harmless safeguard for
-- portability to older servers. IF NOT EXISTS makes re-runs idempotent.
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ----------------------------------------------------------------------------
-- transactions — the raw event as submitted via POST /transactions.
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS transactions (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id             VARCHAR(50)  NOT NULL,
    merchant            VARCHAR(100) NOT NULL,
    amount              DECIMAL(12, 2) NOT NULL CHECK (amount >= 0),  -- canonical USD
    is_foreign_merchant BOOLEAN      NOT NULL DEFAULT FALSE,
    location            VARCHAR(100),
    -- What the user actually entered before client-side conversion to USD.
    -- Kept for display/audit only; `amount` above remains the canonical USD value.
    original_currency   VARCHAR(3)   DEFAULT 'USD',
    original_amount     DECIMAL(12, 2) CHECK (original_amount IS NULL OR original_amount >= 0),
    -- status = the transaction lifecycle STATE MACHINE. This is distinct from the
    -- AI's recommendation (fraud_results.decision): the AI only recommends; the
    -- binding decision is made by a user and/or analyst. The AI can never reach a
    -- DECLINED state on its own (a DECLINE recommendation routes to
    -- PENDING_USER_CONFIRMATION, not DECLINED). 'NEW' collapses into 'SCORING'.
    status              VARCHAR(30)  NOT NULL DEFAULT 'SCORING'
                        CHECK (status IN (
                            'SCORING',
                            'COMPLETED',
                            'PENDING_USER_CONFIRMATION',
                            'PENDING_ANALYST_REVIEW',
                            'DECLINED'
                        )),
    -- timestamp = business time of the transaction (may be client-supplied);
    -- created_at = ingestion time (server clock). Kept separate on purpose.
    "timestamp"         TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    created_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

-- Per-user history lookups (the consumer's velocity/avg-amount context build).
CREATE INDEX IF NOT EXISTS idx_transactions_user_ts
    ON transactions (user_id, "timestamp" DESC);

-- Dashboard "latest transactions" feed, newest first.
CREATE INDEX IF NOT EXISTS idx_transactions_created_at
    ON transactions (created_at DESC);

-- Dashboard filter/aggregate by lifecycle state (e.g. ?status=PENDING_ANALYST_REVIEW).
CREATE INDEX IF NOT EXISTS idx_transactions_status
    ON transactions (status, created_at DESC);

-- ----------------------------------------------------------------------------
-- users — accounts for the login/signup gate. `user_id` is the unique handle
-- the person claims at signup and that pre-fills the transaction form; `email`
-- is the unique login identity (stored lowercased). Passwords are never stored
-- in plaintext — password_hash holds a self-describing PBKDF2-SHA256 string.
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS users (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email          VARCHAR(255) NOT NULL,
    user_id        VARCHAR(50)  NOT NULL,
    password_hash  TEXT         NOT NULL,
    created_at     TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_users_email   UNIQUE (email),
    CONSTRAINT uq_users_user_id UNIQUE (user_id)
);

-- ----------------------------------------------------------------------------
-- fraud_results — Claude's structured assessment. Exactly one row per txn.
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS fraud_results (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    transaction_id   UUID NOT NULL REFERENCES transactions(id) ON DELETE CASCADE,
    fraud_score      DECIMAL(5, 4) NOT NULL CHECK (fraud_score >= 0 AND fraud_score <= 1),
    -- decision = the AI's RECOMMENDATION only (never the final outcome). The
    -- binding lifecycle state lives in transactions.status. These are deliberately
    -- separate fields: the AI recommends, humans decide.
    decision         VARCHAR(10) NOT NULL CHECK (decision IN ('APPROVE', 'REVIEW', 'DECLINE')),
    confidence       VARCHAR(10) NOT NULL CHECK (confidence IN ('HIGH', 'MEDIUM', 'LOW')),
    -- Array of {factor, severity, detail} objects exactly as Claude returns them.
    risk_factors     JSONB NOT NULL DEFAULT '[]'::jsonb,
    -- Array of matched pattern name strings.
    patterns_matched JSONB NOT NULL DEFAULT '[]'::jsonb,
    explanation      TEXT NOT NULL,
    ai_model_used    VARCHAR(50) NOT NULL DEFAULT 'claude-sonnet-4-6',
    cache_hit        BOOLEAN NOT NULL DEFAULT FALSE,   -- served from Redis cache?
    inference_ms     INTEGER,                          -- Claude round-trip latency
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    -- One assessment per transaction -> enables idempotent UPSERT on redelivery.
    CONSTRAINT uq_fraud_results_txn UNIQUE (transaction_id)
);

-- Feed/filter by decision (e.g. dashboard ?decision=DECLINE), newest first.
CREATE INDEX IF NOT EXISTS idx_fraud_results_decision_created
    ON fraud_results (decision, created_at DESC);

-- ----------------------------------------------------------------------------
-- analyst_feedback — human-in-the-loop labels. Drives the Redis feedback
-- summary that gets injected into future Claude prompts (no model retraining).
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS analyst_feedback (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    transaction_id   UUID NOT NULL REFERENCES transactions(id)  ON DELETE CASCADE,
    fraud_result_id  UUID NOT NULL REFERENCES fraud_results(id) ON DELETE CASCADE,
    analyst_label    VARCHAR(20) NOT NULL
                     CHECK (analyst_label IN ('CONFIRMED_FRAUD', 'FALSE_POSITIVE')),
    analyst_notes    TEXT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Pull all feedback for a transaction when rendering its detail drawer.
CREATE INDEX IF NOT EXISTS idx_analyst_feedback_txn
    ON analyst_feedback (transaction_id);

-- ----------------------------------------------------------------------------
-- transaction_audit — append-only ledger of every state-machine transition.
-- One row per transition so the dashboard can render a full timeline and we have
-- an auditable record of WHO (AI/USER/ANALYST/SYSTEM) moved the payment and WHY.
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS transaction_audit (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    transaction_id   UUID NOT NULL REFERENCES transactions(id) ON DELETE CASCADE,
    -- old_state is NULL for the very first (ingest) record.
    old_state        VARCHAR(30),
    new_state        VARCHAR(30) NOT NULL,
    actor            VARCHAR(10) NOT NULL
                     CHECK (actor IN ('AI', 'USER', 'ANALYST', 'SYSTEM')),
    -- actor_id = optional identity of the human who acted (no auth in this app).
    actor_id         VARCHAR(100),
    reason           TEXT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Render a transaction's transition timeline in chronological order.
CREATE INDEX IF NOT EXISTS idx_transaction_audit_txn
    ON transaction_audit (transaction_id, created_at);

-- ----------------------------------------------------------------------------
-- ai_chat_sessions — persisted analyst chat threads with Claude.
-- messages is the full JSONB conversation array [{role, content, ...}].
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ai_chat_sessions (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id  VARCHAR(100) NOT NULL,
    messages    JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    -- One row per logical session so /chat can UPSERT by session_id.
    CONSTRAINT uq_chat_sessions_session_id UNIQUE (session_id)
);

CREATE INDEX IF NOT EXISTS idx_chat_sessions_updated
    ON ai_chat_sessions (updated_at DESC);

-- ----------------------------------------------------------------------------
-- updated_at trigger — keeps ai_chat_sessions.updated_at fresh on every write
-- so the chat list can sort by "most recently active" without app-layer clocks.
-- ----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_chat_sessions_updated_at ON ai_chat_sessions;
CREATE TRIGGER trg_chat_sessions_updated_at
    BEFORE UPDATE ON ai_chat_sessions
    FOR EACH ROW
    EXECUTE FUNCTION set_updated_at();

-- ============================================================================
-- End of schema.
-- ============================================================================
