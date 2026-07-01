"""Typed application configuration (single source of truth, validated at import)."""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    """All runtime configuration, loaded from environment / backend/.env."""

    # --- PostgreSQL ---
    DATABASE_URL: str = Field(..., description="Async SQLAlchemy DSN (postgresql+asyncpg://...).")
    SYNC_DATABASE_URL: str = Field(..., description="Sync DSN for Alembic/migrations.")

    # --- Redis ---
    REDIS_URL: str = Field("redis://localhost:6379")

    # --- Kafka ---
    KAFKA_BOOTSTRAP_SERVERS: str = Field("localhost:9092")
    KAFKA_TOPIC_RAW: str = Field("transactions.raw")
    KAFKA_TOPIC_SCORED: str = Field("transactions.scored")
    KAFKA_CONSUMER_GROUP: str = Field("fraudshield-scorers")

    # --- LLM provider selection: "gemini" (default) or "anthropic" ---
    LLM_PROVIDER: str = Field("gemini")

    # --- Google AI Studio / Gemini ---
    GOOGLE_API_KEY: str = Field("your_google_ai_studio_key_here")
    GEMINI_MODEL: str = Field("gemini-2.5-flash-lite")

    # --- Anthropic / Claude (alternate provider) ---
    ANTHROPIC_API_KEY: str = Field("your_api_key_here")
    ANTHROPIC_BASE_URL: str = Field("https://capi.aerolink.lat/")
    ANTHROPIC_MODEL: str = Field("claude-opus-4-8")

    @property
    def ACTIVE_MODEL(self) -> str:
        """Model id for whichever provider is active — used for row metadata."""
        return self.ANTHROPIC_MODEL if self.LLM_PROVIDER == "anthropic" else self.GEMINI_MODEL

    # --- Behavioral / pipeline tunables ---
    DEDUP_TTL_SECONDS: int = Field(86_400)
    AI_CACHE_TTL_SECONDS: int = Field(3_600)
    VELOCITY_1H_TTL_SECONDS: int = Field(3_600)
    VELOCITY_24H_TTL_SECONDS: int = Field(86_400)

    # New users (no behavioral history) cannot be auto-approved above this amount.
    NEW_USER_AMOUNT_LIMIT: float = Field(100.0)

    # Read backend/.env; ignore unrelated extra env vars (e.g. NEXT_PUBLIC_*).
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

@lru_cache
def get_settings() -> Settings:
    """Cached accessor so the .env file is parsed exactly once per process."""
    return Settings()

settings = get_settings()