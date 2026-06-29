# 🛡️ FraudShield Lite AI

Real-time transaction fraud detection with an **LLM as the scoring engine**. Every
transaction streams through Kafka, gets enriched with behavioral context from
Redis, is scored by an LLM (returning a structured fraud assessment), persisted to
Postgres, and pushed to a live Next.js dashboard over WebSocket — all in seconds.

The LLM layer is **provider-agnostic**: it runs on Google Gemini by default and
swaps to Anthropic Claude with a single `.env` flag. No downstream code names a
vendor.

---

## Table of contents
- [Architecture](#architecture)
- [Tech stack](#tech-stack)
- [Features](#features)
- [Prerequisites](#prerequisites)
- [Quick start](#quick-start)
- [Configuration](#configuration)
- [API reference](#api-reference)
- [Design decisions](#design-decisions)
- [Troubleshooting](#troubleshooting)

---

## Architecture

```
                          ┌─────────────────────────────────────────────┐
                          │                FRONTEND (Next.js)            │
                          │  StatsCards · TransactionFeed · Drawer       │
                          │  TransactionForm · AIAnalystChat             │
                          └───────┬──────────────────────────▲──────────┘
                       REST/JSON  │            WebSocket      │ token stream
                                  ▼            (alerts)       │ (/chat)
   ┌──────────────────────────────────────────────────────────────────────┐
   │                          FastAPI  (backend/main.py)                    │
   │                                                                        │
   │  POST /transactions ─┐                          ┌─ GET /stats          │
   │  GET  /transactions  │                          │  POST /feedback      │
   │  GET  /transactions/{id}                        │  POST /chat (stream) │
   └──────────┬───────────┴──────────────────────────┴──────────┬─────────┘
              │ publish (keyed by user_id)                       │
              ▼                                                  │
        ┌───────────┐   transactions.raw    ┌──────────────────────────────┐
        │   Kafka   │ ────────────────────► │   Consumer (kafka_consumer)  │
        │  (3 part.)│ ◄──────────────────── │  poll → context → score →    │
        └───────────┘   transactions.scored │  DB upsert → WS broadcast    │
                                            └───┬───────────┬──────────┬────┘
                                    Redis ctx   │           │ scorer   │ persist
                                  ┌─────────────▼──┐  ┌──────▼──────┐  ▼
                                  │     Redis      │  │  LLM (AI)   │ ┌──────────┐
                                  │ velocity/dedup │  │  Gemini /   │ │ Postgres │
                                  │ context/cache  │  │  Claude     │ │  5 tables│
                                  │ feedback summ. │  └─────────────┘ └──────────┘
                                  └────────────────┘
```

**Request lifecycle**

1. `POST /transactions` → idempotency check (Redis), persist raw row (Postgres),
   publish to `transactions.raw` keyed by `user_id`, return `202` immediately.
2. The **consumer** polls the topic, builds the user's behavioral context from
   Redis (velocity, running average, usual merchants, prior analyst feedback),
   and calls the scorer.
3. The **scorer** checks the Redis assessment cache keyed on `transaction_id`
   (a hit only on a retry of the same id); on a miss it prompts the LLM (JSON mode)
   and parses a `FraudAssessment` (score, decision, confidence, risk factors,
   patterns, explanation).
4. The assessment is **UPSERTed** into `fraud_results` (idempotent on
   `transaction_id`). The AI's recommendation then advances the transaction's
   lifecycle **status** (SCORING → COMPLETED / PENDING_ANALYST_REVIEW /
   PENDING_USER_CONFIRMATION) — a guarded, audited transition — and **every**
   state change is broadcast over WebSocket to all dashboards.
5. Humans make the binding decision: a flagged cardholder confirms or cancels, an
   analyst approves or rejects (see [Decision workflow](#decision-workflow-ai-recommends-humans-decide)).
   Separately, analysts can label results via `POST /feedback`; the label is folded
   into a Redis summary injected into that user's future prompts — a
   **no-retraining feedback loop**.

---

## Tech stack

| Layer        | Technology |
|--------------|------------|
| Frontend     | Next.js 16 (App Router), React 19, TypeScript, Tailwind v4 |
| Backend      | FastAPI, Pydantic v2, SQLAlchemy 2.0 (async), Uvicorn |
| Streaming    | Apache Kafka (confluent-kafka), Zookeeper |
| Datastore    | PostgreSQL (asyncpg), Redis (redis-py async) |
| AI           | Google Gemini (`google-generativeai`) · Anthropic Claude (`anthropic`) — swappable |
| Infra        | Docker Compose (Kafka, ZK, Postgres, Redis, Kafka UI) |

---

## Features

- **Real-time scoring pipeline** — Kafka decouples ingestion from scoring; per-user
  keying preserves ordering for velocity state.
- **LLM fraud assessment** — structured JSON output: score, decision band
  (APPROVE/REVIEW/DECLINE), confidence, risk factors, matched patterns, plain
  explanation.
- **Behavioral context** — velocity counters, running average amount (Welford),
  usual-merchant memory, merchant fraud rates — all sub-ms from Redis.
- **Per-transaction idempotency cache** — the AI assessment is cached on the unique
  `transaction_id`, so **every new transaction gets a fresh LLM evaluation** against
  the latest behavioral context; only a retry/redelivery of the *same* id reuses the
  result (live hit-rate surfaced in `/stats`).
- **AI-recommends / humans-decide state machine** — the AI never auto-completes or
  declines a payment; a guarded, audited lifecycle (user confirmation + analyst
  review) makes the binding call. Full transition timeline per transaction.
- **No-retraining feedback loop** — analyst labels reshape future prompts per user.
- **Streaming AI analyst chat** — converse about flagged transactions; pinned
  transactions become grounding context; multi-turn memory persisted per session.
- **Live dashboard** — KPI cards, real-time feed (WS + self-healing REST poll),
  detail drawer, feedback controls, transaction submitter with presets.
- **Resilient by design** — Redis outages degrade context (never crash); an LLM
  failure persists a safe REVIEW fallback (no transaction lost); WS auto-reconnects
  with backoff.

---

## Prerequisites

- **Docker Desktop** (Compose v2+)
- **Python 3.10+** (a venv lives at `backend/.venv`)
- **Node.js 20+** / npm
- **Google AI Studio API key** (free): https://aistudio.google.com/apikey

---

## Quick start

### 1. Infrastructure
```bash
docker compose up -d        # Kafka, Zookeeper, Postgres, Redis, Kafka UI
docker compose ps           # all should be "healthy"
```
Postgres auto-runs `backend/db/init.sql` on first boot (creates the 4 tables).
Kafka UI is at http://localhost:8080.

### 2. Backend
```bash
cd backend
# set your key in .env:  GOOGLE_API_KEY=...   (LLM_PROVIDER=gemini)
.venv/Scripts/python -m uvicorn main:app --host 127.0.0.1 --port 8000
# (macOS/Linux: .venv/bin/python ...)
```
The app creates the Kafka topics and launches the scoring consumer on startup.
Health: http://localhost:8000/health · API docs: http://localhost:8000/docs

### 3. Frontend
```bash
cd frontend
npm install                 # ⚠️ see Troubleshooting if this errors with EALLOWSCRIPTS
npm run dev                 # http://localhost:3000
```

Open http://localhost:3000, click a preset in **Submit Transaction**, and watch it
score live in the feed.

---

## Configuration

All backend config is in `backend/.env` (typed/validated by `config.py`):

| Var | Default | Notes |
|-----|---------|-------|
| `LLM_PROVIDER` | `gemini` | `gemini` or `anthropic` — the only switch needed |
| `GOOGLE_API_KEY` | — | required when provider=gemini |
| `GEMINI_MODEL` | `gemini-2.5-flash-lite` | 2.0-flash has free-tier limit 0 |
| `ANTHROPIC_API_KEY` / `ANTHROPIC_BASE_URL` / `ANTHROPIC_MODEL` | — | used when provider=anthropic |
| `DATABASE_URL` | `postgresql+asyncpg://fraud:fraud@localhost:5432/fraudshield` | |
| `REDIS_URL` | `redis://localhost:6379` | |
| `KAFKA_BOOTSTRAP_SERVERS` | `localhost:9092` | |
| `*_TTL_SECONDS` | — | dedup / cache / velocity windows |

Frontend config is in `frontend/.env.local`:
`NEXT_PUBLIC_API_URL=http://localhost:8000`, `NEXT_PUBLIC_WS_URL=ws://localhost:8000`.

**Switching to Claude:** set `LLM_PROVIDER=anthropic` + a valid key + base URL.
No code changes — the scorer and chat layers resolve the provider at runtime.

---

## Decision workflow (AI recommends, humans decide)

The AI **never** has authority to complete or permanently decline a payment. Its
output is a *recommendation*; the binding outcome is a separate state machine on
`transactions.status`, advanced by humans and recorded in an append-only
`transaction_audit` ledger.

```
            (ingest)        (AI scores)
   SCORING ───────────┬─ APPROVE ─► COMPLETED                       (terminal)
                      ├─ REVIEW  ─► PENDING_ANALYST_REVIEW
                      └─ DECLINE ─► PENDING_USER_CONFIRMATION
   PENDING_USER_CONFIRMATION ──┬─ user Cancel ──────────► DECLINED  (terminal)
                               └─ user Continue Anyway ─► PENDING_ANALYST_REVIEW
   PENDING_ANALYST_REVIEW ─────┬─ analyst Approve ──────► COMPLETED (terminal)
                               └─ analyst Reject ───────► DECLINED  (terminal)
```

A DECLINE recommendation routes the cardholder to a "this payment appears
suspicious" screen (Continue Anyway / Cancel); continuing only sends it to an
analyst — it does not complete the payment. `transactions.status` (the state) and
`fraud_results.decision` (the AI recommendation) are deliberately separate fields.

## API reference

| Method | Path | Purpose |
|--------|------|---------|
| `GET`  | `/health` | Per-dependency liveness (kafka/db/redis/ai) |
| `POST` | `/transactions` | Ingest a transaction → `202 {transaction_id, status}` |
| `GET`  | `/transactions` | Paginated list, `?status=` (and `?decision=`) filter |
| `GET`  | `/transactions/{id}` | Transaction + status + assessment + feedback + **audit timeline** |
| `POST` | `/transactions/{id}/confirm` | USER "Continue Anyway" → PENDING_ANALYST_REVIEW |
| `POST` | `/transactions/{id}/cancel` | USER "Cancel" → DECLINED |
| `POST` | `/transactions/{id}/approve` | ANALYST approve → COMPLETED |
| `POST` | `/transactions/{id}/reject` | ANALYST reject → DECLINED |
| `POST` | `/feedback` | Record analyst label (CONFIRMED_FRAUD / FALSE_POSITIVE) |
| `POST` | `/chat` | Streaming AI-analyst chat (text/plain) |
| `GET`  | `/stats` | Dashboard KPIs (today's status breakdown + cache hit rate) |
| `WS`   | `/ws/alerts` | Live push of **every** state transition (scoring + human actions) |

The four state-action endpoints take an optional `{reason?, actor_id?}` body,
guard the source state (returning **409** on an illegal transition), write an
audit row, and broadcast the new state over the WebSocket.

---

## Design decisions

- **LLM as scoring engine, not a  classifier service.** The fraud rubric lives in a
  prompt; the model returns structured JSON. This trades a tiny bit of latency
  (mitigated by the cache) for explainability — every decision ships with risk
  factors and a human-readable rationale.
- **Provider abstraction.** `ai/scorer_factory.py` + `ai/base.py` (Protocol) mean
  the consumer and endpoints depend on a shape, not a vendor. Gemini and Claude are
  drop-in. SDKs are imported lazily so only the active provider's package is needed.
- **Kafka keyed by `user_id`.** Per-key ordering keeps a user's velocity and running
  average sequentially consistent; different users parallelize across partitions.
- **AI recommends, humans decide.** The AI can never complete or permanently
  decline a payment — its recommendation only sets a lifecycle *status* that humans
  advance. `transactions.status` (state machine) and `fraud_results.decision` (AI
  recommendation) are separate fields; `transaction_state.py` is the single source
  for transition rules + the audited `apply_transition()` used by both the consumer
  and the action endpoints. (See [Decision workflow](#decision-workflow-ai-recommends-humans-decide).)
- **Idempotency at the transaction_id level (not content).** Every POST is a
  distinct financial event with its own id and a fresh AI evaluation — two identical
  charges (same user/merchant/amount) are both scored, because the behavioral context
  may have shifted. Reuse happens ONLY on a retry of the same id: the AI cache is
  keyed on `transaction_id`, `fraud_results.transaction_id` is UNIQUE so the consumer
  UPSERTs (Kafka at-least-once → exactly-once at the DB), and the AI status transition
  is guarded to `expected_from={SCORING}` so a redelivery can't clobber a human action.
- **Fail-soft, never fail-closed.** Redis errors return safe defaults; an LLM
  failure persists a REVIEW fallback and still advances the offset. No transaction
  is silently dropped.
- **Raw SQL over ORM models.** The schema is owned by `init.sql` and payloads are
  JSONB blobs from the LLM; a thin async Core layer avoids ORM drift.

---

## Troubleshooting

- **`npm install` fails with `EALLOWSCRIPTS`** — this machine's user `~/.npmrc` has
  `allow-scripts=@anthropic-ai/claude-code`, which npm 11 rejects during a
  project-scoped install. Work around it without touching the global config:
  ```bash
  npm install --userconfig /tmp/empty_npmrc   # an empty file
  ```
- **Gemini `429 RESOURCE_EXHAUSTED`** — the free tier caps `gemini-2.5-flash-lite`
  at ~20 requests/day. Scoring degrades to a REVIEW fallback and chat shows a
  graceful error; quota resets daily. Use a billed key or switch providers for
  heavy use.
- **`/health` shows a dependency `false`** — confirm `docker compose ps` is all
  healthy; the backend reaches services at `localhost` on their published ports.
- **`anthropic` provider errors with `proxies=`** — keep `httpx==0.26.0` pinned
  (anthropic 0.39.0 passes `proxies=`, removed in httpx ≥0.28). Already in
  `requirements.txt`.

---

Built as a learning project demonstrating an end-to-end, LLM-in-the-loop streaming
system. See `BUILD_PROGRESS.md` for the phase-by-phase build log and verification
notes.
