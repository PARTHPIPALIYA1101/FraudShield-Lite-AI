# FraudShield Lite AI — Build Progress

Tracks every phase/step, what file(s) it produced, and verification status.
Updated as we go. Use this to resume if a step is blocked (e.g. Claude API key
error during a live-call verification).

**Legend:** ✅ done & verified · 🟡 code written, verification blocked · ⬜ not started

**Key config:** Provider-agnostic LLM layer via `LLM_PROVIDER` (`gemini` | `anthropic`).
**ACTIVE = Gemini** (Google AI Studio), model `gemini-2.5-flash-lite` (free-tier quota;
2.0-flash has limit 0). Anthropic/Aerolink kept as alternate but proxy is Claude-Code-CLI-only.
Downstream code imports the scorer from `ai/scorer_factory.py` — never names a vendor.

---

## Phase 1 — Infrastructure
| Step | Item | File(s) | Status |
|------|------|---------|--------|
| 1.1 | Docker stack (Kafka, ZK, PG, Redis, Kafka UI) | `docker-compose.yml` | ✅ |
| 1.2 | DB schema, 4 tables | `backend/db/init.sql` | ✅ |
| 1.3 | Async SQLAlchemy engine + session + config | `backend/db.py`, `backend/config.py`, `backend/.env`, `backend/requirements.txt` | ✅ |
| 1.4 | Redis helpers (dedup, velocity, context, feedback) | `backend/redis_client.py` | ✅ |
| 1.5 | Pydantic schemas | `backend/models.py` | ✅ |
| 1.6 | FastAPI skeleton + live `/health` | `backend/main.py` | ✅ |

## Phase 2 — AI Scoring Engine
| Step | Item | File(s) | Status |
|------|------|---------|--------|
| 2.1 | Dynamic prompt assembly + system prompt | `backend/ai/prompt_builder.py`, `backend/ai/__init__.py` | ✅ |
| 2.2 | Response parser + fallback | `backend/ai/response_parser.py` | ✅ |
| 2.3 | Redis cache for AI responses | `backend/ai/cache_manager.py` | ✅ |
| 2.4 | Provider-agnostic scorers + factory | `backend/ai/base.py`, `backend/ai/gemini_scorer.py`, `backend/ai/claude_scorer.py`, `backend/ai/scorer_factory.py` | ✅ |
| 2.5 | Live test: 3 cases via Gemini | — | ✅ **PASSED (Gemini 2.5-flash-lite)** |

### ✅ Step 2.5 resolved — pivoted Anthropic → Google Gemini
Aerolink proxy was Claude-Code-CLI-only (returned "Please use Claude Code CLI" to SDK
calls). Pivoted to **Google AI Studio / Gemini** behind a provider-agnostic scoring layer.
Live results: A) APPROVE 0.05 · B) DECLINE 0.95 (5 risk factors) · C) DECLINE 0.85.
JSON mode = zero parse fallbacks. Latency 2.1–4.8s (validates the cache design).

**Provider swap is now a one-line `.env` change** (`LLM_PROVIDER=gemini|anthropic`).
History kept for reference: a real `sk-ant-` key + `ANTHROPIC_BASE_URL=https://api.anthropic.com`
would re-enable Claude with no code changes.

### Env setup notes (done this session)
- venv created at `backend/.venv` (Python 3.10.11).
- Installed: anthropic==0.39.0, pydantic==2.5.3, pydantic-settings==2.1.0, redis==5.0.1, **httpx==0.26.0**.
- ⚠️ httpx MUST stay pinned to 0.26.0 — anthropic 0.39.0 passes `proxies=` to httpx, which
  httpx ≥0.28 removed (`TypeError: ... unexpected keyword argument 'proxies'`). Already in requirements.txt.

## Phase 3 — Kafka Pipeline
> ✅ **INFRA UNBLOCKED (2026-06-27):** Docker Desktop now installed (Docker 29.5.3,
> Compose v5.1.4). `docker compose up -d` brings up Postgres/Redis/Kafka/ZK/Kafka-UI
> all healthy; `init.sql` auto-created the 4 tables. Phase 3 verified live end to end.

| Step | Item | File(s) | Status |
|------|------|---------|--------|
| 3.1 | Producer + topic creation | `backend/kafka_producer.py` | ✅ |
| 3.2 | `POST /transactions` + GET list/detail + lifespan (topics + consumer task) | `backend/main.py` | ✅ |
| 3.3 | Consumer (poll→context→score→DB upsert→scored→WS) | `backend/kafka_consumer.py` | ✅ |
| 3.4 | WebSocket manager (fan-out, prune-on-fail) | `backend/websocket_manager.py` | ✅ |
| 3.5 | End-to-end test | — | ✅ **PASSED (live, Gemini)** |

### ✅ Step 3.5 — full pipeline verified live (Gemini 2.5-flash-lite)
POST `/transactions` → Kafka `transactions.raw` → consumer → Gemini → Postgres
`fraud_results` (idempotent UPSERT) → `transactions.scored` → WS `/ws/alerts`.
- **Scoring:** suspicious txns scored DECLINE 0.85–0.95; cold-start new users skew
  cautious (no behavioral baseline yet) — expected, not a bug.
- **WebSocket:** live alert frame received for a DECLINE (DarkBazaarRU 0.95).
- **Idempotency:** identical-content repost returns the original id + `status:"duplicate"`
  (Redis `claim_fingerprint` SET-NX storing the txn id as value).
- **AI cache:** $300 vs $310 same merchant → same bucketed key → 2nd row `cache_hit=t,
  inference_ms=0`.
- **Reads:** `GET /transactions` (pagination + `?decision=` filter) and
  `GET /transactions/{id}` (with risk_factors + feedback) all return correctly.
- New helper: `redis_client.claim_fingerprint()`. Added `logging.basicConfig` in
  `main.py` so consumer scoring lines are visible.

## Phase 4 — Extra AI Features
| Step | Item | File(s) | Status |
|------|------|---------|--------|
| 4.1 | `POST /feedback` + Redis feedback context | `backend/main.py` | ✅ |
| 4.2 | `POST /chat` streaming (provider-agnostic) | `backend/main.py`, `backend/ai/chat.py` | ✅ |
| 4.3 | `GET /stats` | `backend/main.py` | ✅ |

### ✅ Phase 4 verified live (2026-06-27, Gemini)
- **4.1** `POST /feedback`: persists `analyst_feedback` row (label + notes) and folds
  the label into the Redis feedback summary (`record_feedback`) so future prompts for
  that user carry it — no-retraining loop. Guards: 404 unknown txn, 409 not-yet-scored.
  Verified: DB row + `feedback:{user}` summary string + surfaced in `/transactions/{id}`.
- **4.2** `POST /chat`: `StreamingResponse` (text/plain) via new provider-agnostic
  `ai/chat.py` (`stream_answer` → Gemini `start_chat`/`send_message_async(stream=True)`;
  Anthropic branch kept). Prepends pinned-txn context block; persists session to
  `ai_chat_sessions` (UPSERT, stores RAW user msg). Verified: live token stream grounded
  in context ($4200/0.85), **multi-turn memory** recalled the amount on turn 2, 4 msgs
  persisted, `updated_at` trigger fired. No Claude key needed — Gemini streams natively.
- **4.3** `GET /stats`: one Postgres aggregate over today's txns (total/flagged/fraud_rate/
  avg_score/avg_inference_ms) + live Redis `cache_hit_rate`. Verified: output matched a
  direct DB cross-check exactly (7 today, 0.8357 avg, 2092.7ms; cache_hit_rate 0.1429).

## Phase 5 — Frontend
> Scaffold: **Next.js 16.2.9 / React 19 / Tailwind v4**, App Router, `@/*` alias,
> `frontend/`. ⚠️ npm install needs `--userconfig /tmp/empty_npmrc` to bypass the
> machine's user `~/.npmrc` (`allow-scripts=@anthropic-ai/claude-code`, which npm 11
> rejects on project installs). Dev: `cd frontend && npm run dev` (→ localhost:3000).

### ✅ Step 5.1 — setup + typed contract + API client (typecheck + prod build pass)
- `frontend/lib/types.ts` — TS mirror of backend/models.py (enums as string unions;
  REST `*Out` shapes; plus `AlertMessage`/`AlertTransaction` = the consumer's WS
  broadcast shape, which differs from REST: Kafka envelope + raw FraudAssessment).
- `frontend/lib/api.ts` — single fetch wrapper (`ApiError` carries status for 409
  not-scored-yet), REST fns (health/stats/transactions CRUD/feedback), `streamChat`
  (ReadableStream reader over text/plain, AbortSignal-cancelable), `wsAlertsUrl()`.
- `frontend/.env.local` — `NEXT_PUBLIC_API_URL=:8000`, `NEXT_PUBLIC_WS_URL=ws://:8000`.
- Verified: `tsc --noEmit` exit 0; `npm run build` ✓ compiled + TS check pass.

### ✅ Step 5.2 — useWebSocket hook (typecheck + build pass)
- `frontend/lib/hooks/useWebSocket.ts` — subscribes to `/ws/alerts`, parses
  `AlertMessage`, exposes `{status, alerts, lastAlert, clear}`. Exponential backoff
  + full jitter reconnect (cap 30s, resets on open); StrictMode-safe via refs (no
  double sockets); `onAlert` read through a ref so inline callbacks don't churn the
  socket; teardown cancels pending reconnect + nulls handlers before close.

### ✅ Step 5.3 — StatsCards + shared format helpers (typecheck + build pass)
- `frontend/lib/format.ts` — `formatCurrency/Percent/Latency/RelativeTime` +
  `decisionColors()` / `severityClasses()` (Tailwind fragment maps reused by all
  later components — single source for the decision→color scheme).
- `frontend/components/StatsCards.tsx` — 6 KPI cards from `GET /stats`, 5s polling,
  skeleton on first load, non-destructive error banner (keeps last good values).
  `refreshKey` prop forces an immediate refresh after a txn submit.
- Theme: `globals.css` set to a fixed dark "ops console" base (alert accents stay
  high-contrast regardless of OS pref).
- Verified by typecheck + build; live visual confirmation deferred to 5.10 wiring.

### ✅ Steps 5.4 + 5.5 — TransactionFeed + AIScoreCard (typecheck + build pass)
- `frontend/components/AIScoreCard.tsx` — full assessment view; prop is the
  structural union `FraudResult | FraudAssessment` (shared fields). Decision-colored
  score bar, decision/confidence badges, severity-coded risk factors, matched-pattern
  chips, explanation, and auditable metadata (model/latency/cache). `compact` mode.
- `frontend/components/TransactionFeed.tsx` — live list merging TWO sources into a
  `Map<id, FeedItem>`: REST poll of `GET /transactions` (5s, full picture incl.
  APPROVE, self-healing) + `useWebSocket` (instant push for flagged txns). Adapters
  `fromRest`/`fromAlert` normalize the differing shapes; merge prefers a scored
  version and keeps `live` sticky. Controlled selection (`selectedId`/`onSelect`),
  client+server decision filter, relative time, "scoring…" state for unscored rows.

### ✅ Steps 5.6 + 5.7 + 5.8 — Drawer / FeedbackButtons / Form (typecheck + build pass)
- `frontend/components/FeedbackButtons.tsx` (5.7) — CONFIRMED_FRAUD / FALSE_POSITIVE
  + optional notes → `POST /feedback`. Handles the 409 not-scored-yet case (stays
  disabled w/ explanation), success confirmation, shows existing labels. Disabled
  until `scored`. Calls `onSubmitted` to refresh the drawer.
- `frontend/components/TransactionDrawer.tsx` (5.6) — right slide-in panel; fetches
  `GET /transactions/{id}`, composes facts + `AIScoreCard` + `FeedbackButtons`.
  Polls every 2s WHILE unscored (so the score appears without reopening), stops once
  scored. Closes on backdrop click + Escape.
- `frontend/components/TransactionForm.tsx` (5.8) — `POST /transactions` with 4
  one-click presets (Normal/Foreign-High/Risky-Merchant/Velocity), all fields
  editable. Surfaces queued vs duplicate status; hands new id up via `onSubmitted`
  so the page can refresh + open the drawer.

| Step | Item | Status |
|------|------|--------|
| 5.1 | Next.js setup + types + api.ts | ✅ |
| 5.2 | useWebSocket (auto-reconnect) | ✅ |
| 5.3 | StatsCards | ✅ |
| 5.4 | TransactionFeed | ✅ |
| 5.5 | AIScoreCard | ✅ |
| 5.6 | TransactionDrawer | ✅ |
| 5.7 | FeedbackButtons | ✅ |
| 5.8 | TransactionForm (4 presets) | ✅ |
| 5.9 | AIAnalystChat (streaming) | ✅ |
| 5.10 | Wire page.tsx + /chat | ✅ |

### ✅ Steps 5.9 + 5.10 — AIAnalystChat + page wiring (built + RUN LIVE)
- `frontend/components/AIAnalystChat.tsx` (5.9) — streaming chat over `POST /chat`
  via `api.streamChat`; per-mount `session_id` (multi-turn memory), fills the
  assistant turn live as tokens arrive, autoscroll, Enter-to-send, AbortController
  cleanup, pinned-context badge. Graceful error bubble on failure.
- `frontend/app/page.tsx` (5.10) — full dashboard: header + live health dot, KPI
  row, 3-pane work area (form · feed · chat), drawer overlay. Shared state:
  `selectedId` (drives drawer + chat context) + `refreshKey` (submit → instant
  stats/feed refresh). Removed CRA boilerplate; set `<title>`; dark ops theme.
- **Live run (localhost:3000 + backend :8000):** page serves HTTP 200 with all panes;
  CORS preflight + GET scoped to `http://localhost:3000` ✓. End-to-end data flow
  (submit → feed poll → drawer detail → chat) exercised against the live stack.
  Dedup correctly returned `duplicate` on a repeat. Removed a stray empty root
  `package-lock.json` (Turbopack workspace-root warning).
- ⚠️ **Gemini free-tier daily quota hit** (20 req/day, `gemini-2.5-flash-lite`) during
  testing → **both degradation paths verified live**: scoring falls back to REVIEW 0.5
  (`api_failure_assessment`, no txn lost) and `/chat` yields a graceful error bubble.
  Happy-path chat/scoring already verified in 3.5 + 4.2. Quota resets daily; final
  fresh-LLM demo (6.4) just needs quota headroom.

## Phase 6 — Polish
| Step | Item | Status |
|------|------|--------|
| 6.1 | README + architecture diagram | ✅ |
| 6.2 | Error states | ✅ |
| 6.3 | Loading skeletons | ✅ |
| 6.4 | Final demo run | ✅
 |

### ✅ Phase 6 — polish (typecheck + build + live run pass)
- **6.1** `README.md` (repo root) — overview, ASCII architecture diagram, request
  lifecycle, tech stack, features, prereqs, quick start (infra/backend/frontend),
  config table + provider swap, API reference, design decisions, troubleshooting
  (npm EALLOWSCRIPTS workaround, Gemini 429 quota, httpx pin).
- **6.2** Error states audited across all components: StatsCards banner (keeps last
  values), TransactionFeed **"stale" badge** on poll failure, drawer load-fail +
  "scoring in progress", FeedbackButtons 409/error lines, form error line, chat
  error bubble, header **health dot** (emerald/amber/red incl. "API offline").
- **6.3** Loading skeletons: StatsCards (6 cards) + drawer (blocks) already done;
  added a **6-row skeleton to TransactionFeed** initial load (distinct from the
  empty state).
- **6.4** Final run: `npm run build` ✓; live stack — frontend HTTP 200, backend
  health all-green, `/stats` (15 today, cache_hit 0.133) + `/transactions` feed
  serving scored rows. Fresh-LLM calls gated by Gemini daily quota (degrades
  gracefully, see 5.10 note); all non-LLM paths verified live.

> **🎉 BUILD COMPLETE — all 6 phases done.** Run: `docker compose up -d`, then
> `uvicorn main:app` in `backend/`, then `npm run dev` in `frontend/` → localhost:3000.

---

## Phase 7 — Decision-workflow redesign (AI recommends, humans decide)
Separated the AI recommendation from a binding transaction **state machine** so the
AI can never complete or permanently decline a payment. Plan:
`.claude/plans/modular-prancing-sundae.md`.

| Step | Item | File(s) | Status |
|------|------|---------|--------|
| 7.1 | Schema: `transactions.status` + `transaction_audit` + idempotent startup migration | `backend/db/init.sql`, `backend/migrations.py` | ✅ |
| 7.2 | State-machine core: transitions, guards, audited `apply_transition`, WS event builder | `backend/transaction_state.py` | ✅ |
| 7.3 | Schemas: `TransactionStatus`/`Actor`/`AuditEntry`/`StateAction*`, status on `TransactionOut`, status-based `StatsOut` | `backend/models.py` | ✅ |
| 7.4 | Consumer: SCORING→recommendation status (guarded, idempotent), broadcast every scored txn | `backend/kafka_consumer.py` | ✅ |
| 7.5 | API: 4 action endpoints (confirm/cancel/approve/reject), audit on ingest+detail, `?status=` filter, status `/stats`, migration in lifespan | `backend/main.py` | ✅ |
| 7.6 | Frontend core: status/audit/update types, `statusColors/Label`, action API fns, WS `transaction` event | `frontend/lib/*` | ✅ |
| 7.7 | Frontend UI: `StatusBadge`/`ActionButtons`/`AuditTimeline` + feed (status axis), drawer (warning+actions+timeline), stats, AIScoreCard relabel | `frontend/components/*`, `app/page.tsx` | ✅ |
| 7.8 | End-to-end verification | — | ✅ **PASSED (live, Gemini)** |

### ✅ Phase 7 verified live (2026-06-27)
- **Migration**: ran on startup against the live DB (21 rows). `status` column +
  `transaction_audit` created; backfill mapped APPROVE→COMPLETED (2),
  REVIEW→PENDING_ANALYST_REVIEW (9), DECLINE→PENDING_USER_CONFIRMATION (10); 21
  audit rows seeded. Idempotent (safe every boot).
- **State machine (curl + WS client)**: every path verified with correct WS
  broadcasts + actors + reasons:
  - user confirm → PENDING_ANALYST_REVIEW → analyst approve → COMPLETED
  - user cancel → DECLINED ("Cancelled by User")
  - user confirm → analyst reject → DECLINED
  - guards: illegal transition → **409**, unknown id → **404**
- **Fresh pipeline**: new txn → SCORING (audit: SYSTEM ingested) → consumer →
  Gemini DECLINE 0.85 → **PENDING_USER_CONFIRMATION** by AI (NOT auto-declined) →
  unified `{type:"transaction", status, transition}` WS frame received live.
- **Audit timeline** + **status-based `/stats`** (pending_confirmation /
  pending_review / completed / declined) returned correctly.
- **Frontend**: `tsc --noEmit` ✓, `npm run build` ✓, serves HTTP 200. Feed now
  keyed on status (AI rec shown secondary); drawer shows the suspicious-payment
  warning + Continue/Cancel, analyst Approve/Reject, and the audit timeline.
- **Infra note**: Docker Desktop had stopped between sessions; restarted it, and a
  stale ZK broker-ephemeral node (post-unclean-shutdown `NodeExists`) needed a
  `docker compose down && up` (named volumes preserved → Postgres data intact).

> **🎉 REDESIGN COMPLETE — the AI recommends; users + analysts decide; every move audited.**

---

## Phase 8 — Bugfix: stale AI assessments reused for repeat transactions
**Root cause (two layers):** (1) `ai/cache_manager.build_cache_key()` keyed the AI
cache on a *risk-shape bucket* `{merchant, amount_bucket, velocity_bucket,
ratio_bucket, foreign}`, so two DIFFERENT transactions with the same merchant+amount
collided onto one entry → the 2nd reused the 1st's LLM result. (2) `create_transaction`
deduped on a content fingerprint `{user|merchant|amount|foreign}` (Redis SET-NX, 24h),
so a repeat "Amazon 5000" never created a new txn or reached the scorer at all — it
returned the original id with `status:"duplicate"`.

| Item | File(s) | Status |
|------|---------|--------|
| AI cache keyed on `transaction_id` (fresh LLM per new txn; hit only on same-id retry) | `backend/ai/cache_manager.py` | ✅ |
| Cache logging: `txn=… cache_key=… cache=HIT/MISS llm_called=…` | `backend/ai/gemini_scorer.py`, `backend/ai/claude_scorer.py` | ✅ |
| Removed content-fingerprint ingestion dedup (each POST = distinct event) | `backend/main.py` | ✅ |
| Docs (cache semantics, lifecycle, idempotency) | `README.md` | ✅ |

### ✅ Phase 8 verified live (Gemini)
- Bug scenario — SAME user+merchant+amount (`user1/Amazon/5000`) submitted twice →
  two **distinct** ids, both `cache=MISS llm_called=True`, real ~2s Gemini calls
  (`cache_hit=False`). Matrix also passes: same-merchant/diff-amount and
  diff-merchant/same-amount each → fresh LLM call (the diff-amount one independently
  scored REVIEW 0.60 vs the others' DECLINE 0.85 — proof of independent evaluation).
- Idempotency preserved — scoring the **same transaction_id** twice → call#1 MISS
  (2562ms), call#2 **HIT** (0ms, no LLM), identical assessment.
- Cache key is now `fraud:cache:{transaction_id}`; behavioral context in
  `redis_client.py` (velocity/averages/merchants/feedback) is unchanged and still
  cached/reused per the design.

---

## Steps blocked on a working Claude API key
The Aerolink/Claude path is moot now that the active provider is Gemini — every
"blocked" step below was unblocked by the Gemini pivot and the Docker install:

- **2.5** — live scoring of 3 test transactions — ✅ done (Gemini)
- **3.5** — end-to-end pipeline test — ✅ done (Gemini, this session)
- **4.2** — `/chat` streaming endpoint — ⬜ not started; will stream via the active
  provider (Gemini supports streaming), so it is **no longer key-blocked**.

If the key errors (401 = bad/expired key, ConnectError = proxy unreachable):
1. All non-blocked code stays ✅/🟡 — no rework needed.
2. `claude_scorer.py` will still be fully written and **unit-testable with a
   mocked client** (parser + cache + prompt all verifiable offline).
3. Resume the 3 blocked steps once a valid `aero_live_` key is in `backend/.env`.
