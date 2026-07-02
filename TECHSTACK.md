# Tech Stack — FraudShield Lite AI

A real-time, AI-assisted fraud detection platform. Transactions flow through a
Kafka pipeline, get scored by an LLM (Gemini by default, Claude as a drop-in
alternate), and are streamed to a live dashboard over WebSockets. Postgres is the
system of record; Redis holds low-latency state and the AI response cache.

```
Frontend (Next.js) ──HTTP/WS──> Backend (FastAPI)
                                     │
                     ┌───────────────┼────────────────┐
                     │               │                │
                  Kafka          Postgres           Redis
              (raw→scored)   (system of record)  (cache/state)
                     │
              AI Scorer (Gemini / Claude)
```

---

## Backend

| Layer            | Technology            | Version   | Notes |
|------------------|-----------------------|-----------|-------|
| Language         | Python                | 3.11      | Runtime target per `requirements.txt`. |
| Web framework    | FastAPI               | 0.109.0   | REST + WebSocket API (`main.py`). |
| ASGI server      | Uvicorn (`[standard]`)| 0.27.0    | Serves the FastAPI app. |
| Validation       | Pydantic              | 2.5.3     | Request/response models. |
| Settings         | pydantic-settings     | 2.1.0     | Env-driven config (`config.py`). |
| Env loading      | python-dotenv         | 1.0.0     | Loads `.env`. |

### Data & persistence
| Purpose              | Technology         | Version  | Notes |
|----------------------|--------------------|----------|-------|
| Database             | PostgreSQL         | 15-alpine| System of record; seeded via `backend/db/init.sql`. |
| ORM                  | SQLAlchemy `[asyncio]` | 2.0.25 | Async ORM (`models.py`, `db.py`). |
| Async driver         | asyncpg            | 0.29.0   | Async Postgres driver. |
| Sync driver          | psycopg2-binary    | 2.9.9    | Sync/migration driver. |
| Migrations           | Alembic            | 1.13.1   | Schema migrations (`migrations.py`). |
| Cache / state        | Redis              | 7-alpine / redis-py 5.0.1 | Dedup keys, velocity counters, user context, AI cache (`redis_client.py`). |

### Streaming
| Purpose        | Technology            | Version  | Notes |
|----------------|-----------------------|----------|-------|
| Event backbone | Apache Kafka          | cp-kafka 7.5.3 | Topics: `transactions.raw` → `transactions.scored`. |
| Coordination   | ZooKeeper             | cp-zookeeper 7.5.3 | Kafka coordination (non-KRaft). |
| Kafka client   | confluent-kafka       | 2.3.0    | Producer (`kafka_producer.py`) + consumer (`kafka_consumer.py`). |
| Kafka console  | provectuslabs/kafka-ui| v0.7.2   | Dev-only UI at `localhost:8080`. |

### AI layer
Provider-agnostic scoring selected via `LLM_PROVIDER` (`ai/scorer_factory.py`).

| Purpose            | Technology            | Version  | Notes |
|--------------------|-----------------------|----------|-------|
| Default provider   | Google Gemini         | google-generativeai 0.8.3 | `gemini-2.5-flash-lite`; native JSON mode. |
| Alternate provider | Anthropic Claude      | anthropic 0.39.0 | Drop-in swap. |
| HTTP client (pin)  | httpx                 | 0.26.0   | Pinned `<0.28` for anthropic 0.39.0 compatibility. |

AI modules: `base.py`, `scorer_factory.py`, `gemini_scorer.py`, `claude_scorer.py`,
`prompt_builder.py`, `response_parser.py`, `cache_manager.py`, `chat.py`.

Other backend modules: `auth.py`, `policy.py`, `transaction_state.py`,
`websocket_manager.py`.

---

## Frontend

| Layer            | Technology            | Version  | Notes |
|------------------|-----------------------|----------|-------|
| Framework        | Next.js (App Router)  | 16.2.9   | `app/` directory. |
| UI library       | React                 | 19.2.4   | With `react-dom` 19.2.4. |
| Language         | TypeScript            | ^5       | `tsconfig.json`. |
| Styling          | Tailwind CSS          | ^4       | Via `@tailwindcss/postcss`. |
| Linting          | ESLint                | ^9       | `eslint-config-next` 16.2.9. |

Real-time updates via a WebSocket hook (`lib/hooks/useWebSocket.ts`).
Key components: `TransactionFeed`, `AIAnalystChat`, `AIScoreCard`,
`AuditTimeline`, `TransactionForm`, `AuthScreen`.

---

## Infrastructure & tooling

| Purpose            | Technology       | Notes |
|--------------------|------------------|-------|
| Local orchestration| Docker Compose   | `docker-compose.yml` — Kafka, ZooKeeper, Postgres, Redis, Kafka UI. |
| Networking         | Bridge network `fraudshield` | Service name resolution (kafka/postgres/redis). |
| Persistence        | Named volumes `pgdata`, `redisdata` | Survive `docker compose down`. |
| Config             | `.env` / `.env.example` | Environment-driven settings. |

---

## Ports

| Service    | Port  |
|------------|-------|
| Postgres   | 5432  |
| Redis      | 6379  |
| Kafka      | 9092 (host) / 29092 (internal) |
| ZooKeeper  | 2181  |
| Kafka UI   | 8080  |
