// Typed client for the FraudShield backend (single fetch wrapper + chat stream reader).

import type {
  AuthUser,
  ChatRequest,
  FeedbackCreate,
  FeedbackResponse,
  Health,
  LoginRequest,
  PaginatedTransactions,
  SignupRequest,
  StateActionRequest,
  StateActionResponse,
  Stats,
  TransactionCreate,
  TransactionQueued,
  TransactionWithResult,
} from "./types";

export const API_URL =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
export const WS_URL = process.env.NEXT_PUBLIC_WS_URL ?? "ws://localhost:8000";

/** Error carrying the HTTP status so callers can branch (e.g. 409 not-scored-yet). */
export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
    this.name = "ApiError";
  }
}

/**
 * Turn a FastAPI error body into a readable string.
 * `detail` is a plain string for HTTPException (401/404/409/503), but a
 * Pydantic 422 sends an ARRAY of {loc, msg, type} objects — rendering that
 * directly is what produced the "[object Object]" message on a bad email.
 */
function extractDetail(body: unknown): string | null {
  if (!body || typeof body !== "object") return null;
  const detail = (body as { detail?: unknown }).detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    const msgs = detail
      .map((e) => (e && typeof e === "object" ? (e as { msg?: string }).msg : null))
      .filter((m): m is string => Boolean(m))
      // Pydantic prefixes value_error messages with "Value error, "; drop it.
      .map((m) => m.replace(/^Value error,\s*/i, ""));
    if (msgs.length) return msgs.join("; ");
  }
  return null;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    ...init,
  });

  if (!res.ok) {
    // FastAPI errors are {detail: ...}; fall back to status text.
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = extractDetail(body) ?? detail;
    } catch {
      /* non-JSON error body — keep statusText */
    }
    throw new ApiError(res.status, detail);
  }

  // 204/empty bodies -> undefined; otherwise parse JSON.
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

// Auth.
export function signup(body: SignupRequest): Promise<AuthUser> {
  return request<AuthUser>("/auth/signup", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function login(body: LoginRequest): Promise<AuthUser> {
  return request<AuthUser>("/auth/login", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

// System.
export const getHealth = () => request<Health>("/health");
export const getStats = () => request<Stats>("/stats");

// Transactions.
export function createTransaction(
  body: TransactionCreate,
): Promise<TransactionQueued> {
  return request<TransactionQueued>("/transactions", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function listTransactions(params?: {
  page?: number;
  limit?: number;
  status?: string;
  decision?: string;
}): Promise<PaginatedTransactions> {
  const q = new URLSearchParams();
  if (params?.page) q.set("page", String(params.page));
  if (params?.limit) q.set("limit", String(params.limit));
  if (params?.status) q.set("status", params.status);
  if (params?.decision) q.set("decision", params.decision);
  const qs = q.toString();
  return request<PaginatedTransactions>(`/transactions${qs ? `?${qs}` : ""}`);
}

export function getTransaction(id: string): Promise<TransactionWithResult> {
  return request<TransactionWithResult>(`/transactions/${id}`);
}

// State actions — the human decisions the AI may only RECOMMEND.
function stateAction(
  id: string,
  action: "confirm" | "cancel" | "approve" | "reject",
  body?: StateActionRequest,
): Promise<StateActionResponse> {
  return request<StateActionResponse>(`/transactions/${id}/${action}`, {
    method: "POST",
    body: JSON.stringify(body ?? {}),
  });
}

export const confirmTransaction = (id: string, body?: StateActionRequest) =>
  stateAction(id, "confirm", body);
export const cancelTransaction = (id: string, body?: StateActionRequest) =>
  stateAction(id, "cancel", body);
export const approveTransaction = (id: string, body?: StateActionRequest) =>
  stateAction(id, "approve", body);
export const rejectTransaction = (id: string, body?: StateActionRequest) =>
  stateAction(id, "reject", body);

// Feedback.
export function submitFeedback(
  body: FeedbackCreate,
): Promise<FeedbackResponse> {
  return request<FeedbackResponse>("/feedback", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

// Chat — streaming text/plain; calls onChunk per batch, resolves with the full answer.
export async function streamChat(
  body: ChatRequest,
  onChunk: (text: string) => void,
  signal?: AbortSignal,
): Promise<string> {
  const res = await fetch(`${API_URL}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal,
  });

  if (!res.ok || !res.body) {
    throw new ApiError(res.status, res.statusText || "Chat request failed");
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let full = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    const text = decoder.decode(value, { stream: true });
    if (text) {
      full += text;
      onChunk(text);
    }
  }
  // flush any buffered multibyte remainder
  const tail = decoder.decode();
  if (tail) {
    full += tail;
    onChunk(tail);
  }
  return full;
}

// WebSocket.
// WS_URL may be absolute ("ws://localhost:8000", local dev) or a relative path
// ("/api", the nginx-proxied Docker setup). The browser's WebSocket constructor
// requires an ABSOLUTE ws://|wss:// URL, so resolve a relative value against the
// current page origin (mapping http→ws / https→wss).
export function wsAlertsUrl(): string {
  const path = "/ws/alerts";
  if (/^wss?:\/\//i.test(WS_URL)) return `${WS_URL}${path}`;
  if (typeof window !== "undefined") {
    const scheme = window.location.protocol === "https:" ? "wss" : "ws";
    // WS_URL like "/api" (or "") becomes ws://host/api/ws/alerts.
    const base = WS_URL.replace(/\/+$/, "");
    return `${scheme}://${window.location.host}${base}${path}`;
  }
  return `${WS_URL}${path}`; // SSR fallback (socket only opens client-side)
}
