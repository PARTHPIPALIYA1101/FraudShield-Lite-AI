// Typed client for the FraudShield backend (single fetch wrapper + chat stream reader).

export const API_URL =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
export const WS_URL = process.env.NEXT_PUBLIC_WS_URL ?? "ws://localhost:8000";

/** Error carrying the HTTP status so callers can branch (e.g. 409 not-scored-yet). */
export class ApiError extends Error {
  constructor(status, message) {
    super(message);
    this.status = status;
    this.name = "ApiError";
  }
}

/**
 * Turn a FastAPI error body into a readable string.
 * `detail` is a plain string for HTTPException (401/404/409/503), but a
 * Pydantic 422 sends an ARRAY of {loc, msg, type} objects — rendering that
 * directly is what produced the "[object Object]" message on a bad email.
 */
function extractDetail(body) {
  if (!body || typeof body !== "object") return null;
  const detail = body.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    const msgs = detail
      .map((e) => (e && typeof e === "object" ? e.msg : null))
      .filter((m) => Boolean(m))
      // Pydantic prefixes value_error messages with "Value error, "; drop it.
      .map((m) => m.replace(/^Value error,\s*/i, ""));
    if (msgs.length) return msgs.join("; ");
  }
  return null;
}

async function request(path, init) {
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
  if (res.status === 204) return undefined;
  return await res.json();
}

// Auth.
export function signup(body) {
  return request("/auth/signup", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function login(body) {
  return request("/auth/login", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

// System.
export const getHealth = () => request("/health");
export const getStats = () => request("/stats");

// Transactions.
export function createTransaction(
  body,
) {
  return request("/transactions", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function listTransactions(params) {
  const q = new URLSearchParams();
  if (params?.page) q.set("page", String(params.page));
  if (params?.limit) q.set("limit", String(params.limit));
  if (params?.status) q.set("status", params.status);
  if (params?.decision) q.set("decision", params.decision);
  const qs = q.toString();
  return request(`/transactions${qs ? `?${qs}` : ""}`);
}

export function getTransaction(id) {
  return request(`/transactions/${id}`);
}

// State actions — the human decisions the AI may only RECOMMEND.
function stateAction(
  id,
  action,
  body,
) {
  return request(`/transactions/${id}/${action}`, {
    method: "POST",
    body: JSON.stringify(body ?? {}),
  });
}

export const confirmTransaction = (id, body) =>
  stateAction(id, "confirm", body);
export const cancelTransaction = (id, body) =>
  stateAction(id, "cancel", body);
export const approveTransaction = (id, body) =>
  stateAction(id, "approve", body);
export const rejectTransaction = (id, body) =>
  stateAction(id, "reject", body);

// Feedback.
export function submitFeedback(
  body,
) {
  return request("/feedback", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

// Chat — streaming text/plain; calls onChunk per batch, resolves with the full answer.
export async function streamChat(
  body,
  onChunk,
  signal,
) {
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
export function wsAlertsUrl() {
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
