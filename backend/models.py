"""Pydantic v2 schemas — the typed contracts at every API/Kafka/LLM boundary."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


# --- Enums: constrained vocabularies, mirrored by the DB CHECK constraints ---
class Decision(str, Enum):
    APPROVE = "APPROVE"
    REVIEW = "REVIEW"
    DECLINE = "DECLINE"


class Confidence(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class Severity(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class AnalystLabel(str, Enum):
    CONFIRMED_FRAUD = "CONFIRMED_FRAUD"
    FALSE_POSITIVE = "FALSE_POSITIVE"


class TransactionStatus(str, Enum):
    """The lifecycle state machine — distinct from the AI's Decision recommendation."""

    SCORING = "SCORING"
    COMPLETED = "COMPLETED"
    PENDING_USER_CONFIRMATION = "PENDING_USER_CONFIRMATION"
    PENDING_ANALYST_REVIEW = "PENDING_ANALYST_REVIEW"
    DECLINED = "DECLINED"


class Actor(str, Enum):
    """Who performed a state transition (recorded in the audit ledger)."""

    AI = "AI"
    USER = "USER"
    ANALYST = "ANALYST"
    SYSTEM = "SYSTEM"


# Decision thresholds — single source of truth, reused by the response parser.
APPROVE_THRESHOLD = 0.30   # < 0.30 -> APPROVE, > 0.70 -> DECLINE, else REVIEW
DECLINE_THRESHOLD = 0.70


def decision_for_score(score: float) -> Decision:
    """Map a fraud score to its decision band. The authority for thresholds."""
    if score < APPROVE_THRESHOLD:
        return Decision.APPROVE
    if score > DECLINE_THRESHOLD:
        return Decision.DECLINE
    return Decision.REVIEW


# --- Inbound request bodies ---
class TransactionCreate(BaseModel):
    """POST /transactions body."""

    user_id: str = Field(..., min_length=1, max_length=50, examples=["user_123"])
    merchant: str = Field(..., min_length=1, max_length=100, examples=["Amazon"])
    amount: float = Field(..., ge=0, examples=[100.0])
    is_foreign_merchant: bool = Field(default=False)
    location: Optional[str] = Field(default=None, max_length=100, examples=["Mumbai, IN"])

    @field_validator("user_id", "merchant")
    @classmethod
    def _strip_and_check(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("must not be blank")
        return v


class FeedbackCreate(BaseModel):
    """POST /feedback body."""

    transaction_id: UUID
    label: AnalystLabel
    notes: Optional[str] = Field(default=None, max_length=2000)


class ChatRequest(BaseModel):
    """POST /chat body."""

    session_id: str = Field(..., min_length=1, max_length=100)
    message: str = Field(..., min_length=1, max_length=4000)
    context_txn_ids: list[UUID] = Field(default_factory=list)


class KafkaTransactionMessage(BaseModel):
    """The envelope the producer writes and the consumer reads (timestamp = ISO string)."""

    id: str
    user_id: str
    merchant: str
    amount: float
    is_foreign_merchant: bool
    location: Optional[str] = None
    timestamp: str


# --- AI contract: what the LLM returns (parsed/validated) ---
class RiskFactor(BaseModel):
    """One entry in the risk_factors array."""

    factor: str
    severity: Severity
    detail: str


class FraudAssessment(BaseModel):
    """The validated assessment — the LLM's parsed output + pipeline metadata."""

    fraud_score: float = Field(..., ge=0.0, le=1.0)
    decision: Decision
    confidence: Confidence
    risk_factors: list[RiskFactor] = Field(default_factory=list)
    patterns_matched: list[str] = Field(default_factory=list)
    explanation: str

    # Pipeline metadata (not from the LLM JSON); the scorer overrides per call.
    ai_model_used: str = Field(default="claude-opus-4-8")
    cache_hit: bool = Field(default=False)
    inference_ms: int = Field(default=0, ge=0)

    @field_validator("decision", mode="before")
    @classmethod
    def _coerce_decision(cls, v: object, info) -> object:
        # Keep decision authoritative against the score on any construction path.
        score = info.data.get("fraud_score")
        if isinstance(score, (int, float)):
            return decision_for_score(float(score)).value
        return v

    model_config = ConfigDict(use_enum_values=True)


# --- Outbound response shapes ---
class TransactionOut(BaseModel):
    """A persisted transaction row, including its lifecycle status."""

    id: UUID
    user_id: str
    merchant: str
    amount: float
    is_foreign_merchant: bool
    location: Optional[str]
    status: TransactionStatus
    timestamp: datetime
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class FraudResultOut(BaseModel):
    """A persisted fraud_results row."""

    id: UUID
    transaction_id: UUID
    fraud_score: float
    decision: Decision
    confidence: Confidence
    risk_factors: list[RiskFactor]
    patterns_matched: list[str]
    explanation: str
    ai_model_used: str
    cache_hit: bool
    inference_ms: Optional[int]
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class FeedbackOut(BaseModel):
    """A persisted analyst_feedback row."""

    id: UUID
    transaction_id: UUID
    fraud_result_id: UUID
    analyst_label: AnalystLabel
    analyst_notes: Optional[str]
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AuditEntry(BaseModel):
    """One transition in a transaction's state-machine history."""

    id: UUID
    transaction_id: UUID
    old_state: Optional[TransactionStatus] = None
    new_state: TransactionStatus
    actor: Actor
    actor_id: Optional[str] = None
    reason: Optional[str] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class TransactionWithResult(BaseModel):
    """Combined view for GET /transactions list + detail (fraud_result/audit optional)."""

    transaction: TransactionOut
    fraud_result: Optional[FraudResultOut] = None
    feedback: list[FeedbackOut] = Field(default_factory=list)
    audit: list[AuditEntry] = Field(default_factory=list)


class StateActionRequest(BaseModel):
    """Optional body for the user/analyst state-action endpoints."""

    reason: Optional[str] = Field(default=None, max_length=2000)
    actor_id: Optional[str] = Field(default=None, max_length=100)


class StateActionResponse(BaseModel):
    """Response from a state-action endpoint: the new status + the AI recommendation."""

    transaction_id: UUID
    transaction_status: TransactionStatus
    ai_recommendation: Optional[Decision] = None


class TransactionQueued(BaseModel):
    """202 response from POST /transactions."""

    transaction_id: UUID
    status: str = "queued"


class PaginatedTransactions(BaseModel):
    """GET /transactions envelope."""

    items: list[TransactionWithResult]
    total: int
    page: int
    limit: int


class FeedbackResponse(BaseModel):
    """POST /feedback response."""

    success: bool = True


class StatsOut(BaseModel):
    """GET /stats response — KPIs keyed off the transaction lifecycle status."""

    total_today: int
    pending_confirmation: int
    pending_review: int
    completed_today: int
    declined_today: int
    flagged_count: int          # pending_confirmation + pending_review
    fraud_rate: float           # fraction of today's txns not auto-approved
    avg_fraud_score: float
    cache_hit_rate: float
    avg_inference_ms: float


class DependencyHealth(BaseModel):
    """Per-dependency status block inside HealthOut."""

    kafka: bool
    db: bool
    redis: bool
    anthropic_api: bool


class HealthOut(BaseModel):
    """GET /health response ('ok' only if every dependency is healthy)."""

    status: str
    kafka: bool
    db: bool
    redis: bool
    anthropic_api: bool
