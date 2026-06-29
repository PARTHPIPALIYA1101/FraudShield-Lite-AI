// The frontend's view of the backend API contract — mirrors backend/models.py.

// Enums (string-literal unions). Decision = the AI RECOMMENDATION only.
export type Decision = "APPROVE" | "REVIEW" | "DECLINE";
export type Confidence = "HIGH" | "MEDIUM" | "LOW";
export type Severity = "HIGH" | "MEDIUM" | "LOW";
export type AnalystLabel = "CONFIRMED_FRAUD" | "FALSE_POSITIVE";

// TransactionStatus = the lifecycle STATE MACHINE (the binding business state).
export type TransactionStatus =
  | "SCORING"
  | "COMPLETED"
  | "PENDING_USER_CONFIRMATION"
  | "PENDING_ANALYST_REVIEW"
  | "DECLINED";

// Who performed a state transition (recorded in the audit ledger).
export type Actor = "AI" | "USER" | "ANALYST" | "SYSTEM";

// AI contract — what the scorer returns.
export interface RiskFactor {
  factor: string;
  severity: Severity;
  detail: string;
}

/** The scorer's assessment as broadcast over WS (FraudAssessment.model_dump()). */
export interface FraudAssessment {
  fraud_score: number;
  decision: Decision;
  confidence: Confidence;
  risk_factors: RiskFactor[];
  patterns_matched: string[];
  explanation: string;
  ai_model_used: string;
  cache_hit: boolean;
  inference_ms: number;
}

// Persisted rows (the *Out response schemas).
export interface Transaction {
  id: string;
  user_id: string;
  merchant: string;
  amount: number;
  is_foreign_merchant: boolean;
  location: string | null;
  status: TransactionStatus;
  timestamp: string; // ISO-8601
  created_at: string; // ISO-8601
}

/** One transition in a transaction's state-machine history. */
export interface AuditEntry {
  id: string;
  transaction_id: string;
  old_state: TransactionStatus | null;
  new_state: TransactionStatus;
  actor: Actor;
  actor_id: string | null;
  reason: string | null;
  created_at: string;
}

export interface FraudResult {
  id: string;
  transaction_id: string;
  fraud_score: number;
  decision: Decision;
  confidence: Confidence;
  risk_factors: RiskFactor[];
  patterns_matched: string[];
  explanation: string;
  ai_model_used: string;
  cache_hit: boolean;
  inference_ms: number | null;
  created_at: string;
}

export interface Feedback {
  id: string;
  transaction_id: string;
  fraud_result_id: string;
  analyst_label: AnalystLabel;
  analyst_notes: string | null;
  created_at: string;
}

/** Combined view used by GET /transactions and GET /transactions/{id}. */
export interface TransactionWithResult {
  transaction: Transaction;
  fraud_result: FraudResult | null;
  feedback: Feedback[];
  audit: AuditEntry[];
}

export interface PaginatedTransactions {
  items: TransactionWithResult[];
  total: number;
  page: number;
  limit: number;
}

// Request bodies.
export interface TransactionCreate {
  user_id: string;
  merchant: string;
  amount: number;
  is_foreign_merchant?: boolean;
  location?: string | null;
}

export interface TransactionQueued {
  transaction_id: string;
  status: string; // "queued" | "duplicate"
}

export interface FeedbackCreate {
  transaction_id: string;
  label: AnalystLabel;
  notes?: string | null;
}

export interface FeedbackResponse {
  success: boolean;
}

export interface ChatRequest {
  session_id: string;
  message: string;
  context_txn_ids?: string[];
}

/** Optional body for the user/analyst state-action endpoints. */
export interface StateActionRequest {
  reason?: string | null;
  actor_id?: string | null;
}

/** Response from confirm/cancel/approve/reject. */
export interface StateActionResponse {
  transaction_id: string;
  transaction_status: TransactionStatus;
  ai_recommendation: Decision | null;
}

// System / dashboard.
export interface Stats {
  total_today: number;
  pending_confirmation: number;
  pending_review: number;
  completed_today: number;
  declined_today: number;
  flagged_count: number;
  fraud_rate: number;
  avg_fraud_score: number;
  cache_hit_rate: number;
  avg_inference_ms: number;
}

export interface Health {
  status: string; // "ok" | "degraded"
  kafka: boolean;
  db: boolean;
  redis: boolean;
  anthropic_api: boolean;
}

// WebSocket — one unified "transaction" event broadcast on EVERY state transition.
export interface AlertTransaction {
  id: string;
  user_id: string;
  merchant: string;
  amount: number;
  is_foreign_merchant: boolean;
  location: string | null;
  status: TransactionStatus;
  timestamp: string;
}

export interface StateTransition {
  old_state: TransactionStatus | null;
  new_state: TransactionStatus;
  actor: Actor;
  reason: string | null;
}

export interface TransactionUpdateMessage {
  type: "transaction";
  transaction: AlertTransaction;
  fraud_result: FraudAssessment | null;
  status: TransactionStatus;
  transition: StateTransition | null;
}
