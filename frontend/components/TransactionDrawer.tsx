// Right-side detail panel: status, facts, AI assessment, action controls, audit timeline.

"use client";

import { useCallback, useEffect, useState } from "react";

import { getTransaction } from "@/lib/api";
import { formatCurrency, formatRelativeTime } from "@/lib/format";
import type { TransactionWithResult } from "@/lib/types";
import { AIScoreCard } from "./AIScoreCard";
import { ActionButtons } from "./ActionButtons";
import { AuditTimeline } from "./AuditTimeline";
import { FeedbackButtons } from "./FeedbackButtons";
import { StatusBadge } from "./StatusBadge";

interface TransactionDrawerProps {
  transactionId: string | null;
  onClose: () => void;
  /** Called after a state action so the parent can refresh feed + stats. */
  onActionDone?: () => void;
}

const POLL_MS = 2000;
const TERMINAL = new Set(["COMPLETED", "DECLINED"]);

export function TransactionDrawer({
  transactionId,
  onClose,
  onActionDone,
}: TransactionDrawerProps) {
  const [data, setData] = useState<TransactionWithResult | null>(null);
  const [loading, setLoading] = useState(false);

  const open = transactionId !== null;

  const load = useCallback(async () => {
    if (!transactionId) return;
    try {
      setData(await getTransaction(transactionId));
    } catch {
      setData(null);
    }
  }, [transactionId]);

  // Initial + on-id-change load.
  useEffect(() => {
    if (!transactionId) {
      setData(null);
      return;
    }
    setLoading(true);
    setData(null);
    load().finally(() => setLoading(false));
  }, [transactionId, load]);

  // Poll while non-terminal so external changes reflect; stop once settled.
  const status = data?.transaction.status;
  useEffect(() => {
    if (!transactionId || (status && TERMINAL.has(status))) return;
    const t = setInterval(load, POLL_MS);
    return () => clearInterval(t);
  }, [transactionId, status, load]);

  // Close on Escape.
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  // After a state action: reload the drawer AND let the parent refresh the rest.
  const handleActionDone = useCallback(() => {
    load();
    onActionDone?.();
  }, [load, onActionDone]);

  if (!open) return null;

  const txn = data?.transaction;
  const result = data?.fraud_result ?? null;
  const isSuspicious = txn?.status === "PENDING_USER_CONFIRMATION";

  return (
    <div className="fixed inset-0 z-50">
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" onClick={onClose} />
      {/* Panel */}
      <div className="absolute right-0 top-0 flex h-full w-full max-w-md flex-col border-l border-white/10 bg-[#0d0e13] shadow-2xl">
        {/* Header */}
        <div className="flex items-start justify-between border-b border-white/10 px-5 py-4">
          <div className="min-w-0">
            <h2 className="truncate text-base font-semibold text-white/90">
              {txn?.merchant ?? "Transaction"}
            </h2>
            {txn && (
              <div className="mt-1 flex items-center gap-2">
                <StatusBadge status={txn.status} size="sm" />
                <span className="text-xs text-white/40">
                  {txn.user_id} · {formatRelativeTime(txn.created_at)}
                </span>
              </div>
            )}
          </div>
          <button
            onClick={onClose}
            className="ml-3 shrink-0 rounded-md p-1 text-white/40 transition-colors hover:bg-white/10 hover:text-white/80"
            aria-label="Close"
          >
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
              <path d="M6 6l12 12M18 6L6 18" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
            </svg>
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 space-y-6 overflow-y-auto px-5 py-5">
          {loading && !data ? (
            <div className="space-y-3">
              <div className="h-20 animate-pulse rounded-lg bg-white/5" />
              <div className="h-32 animate-pulse rounded-lg bg-white/5" />
            </div>
          ) : !txn ? (
            <p className="text-sm text-white/50">Could not load this transaction.</p>
          ) : (
            <>
              {/* Suspicious-payment warning (the user-confirmation gate) */}
              {isSuspicious && (
                <div className="rounded-xl border border-amber-500/40 bg-amber-500/10 p-4">
                  <div className="flex items-center gap-2 text-sm font-semibold text-amber-300">
                    <span>⚠️</span> This payment appears suspicious.
                  </div>
                  <p className="mt-1 text-xs text-amber-200/80">
                    Our AI flagged this transaction
                    {result ? ` (score ${result.fraud_score.toFixed(2)}, ${result.confidence} confidence)` : ""}.
                    Review the risk factors below, then choose to continue or cancel.
                    Continuing sends it to an analyst — it does not complete the payment.
                  </p>
                </div>
              )}

              {/* Action controls (state-driven) */}
              <div className="rounded-xl border border-white/10 bg-white/5 p-4">
                <div className="mb-3 text-xs font-medium uppercase tracking-wide text-white/50">
                  Decision
                </div>
                <ActionButtons
                  transactionId={txn.id}
                  status={txn.status}
                  onActionDone={handleActionDone}
                />
              </div>

              {/* Transaction facts */}
              <dl className="grid grid-cols-2 gap-x-4 gap-y-3 text-sm">
                <Fact label="Amount" value={formatCurrency(txn.amount)} />
                <Fact label="Foreign" value={txn.is_foreign_merchant ? "Yes" : "No"} />
                <Fact label="Location" value={txn.location ?? "—"} />
                <Fact label="Time" value={new Date(txn.timestamp).toLocaleString()} />
                <Fact label="Transaction ID" value={txn.id} mono span2 />
              </dl>

              {/* AI assessment */}
              <div className="rounded-xl border border-white/10 bg-white/5 p-4">
                <div className="mb-3 text-xs font-medium uppercase tracking-wide text-white/50">
                  AI Assessment (recommendation only)
                </div>
                {result ? (
                  <AIScoreCard result={result} />
                ) : (
                  <div className="flex items-center gap-2 text-sm text-white/50">
                    <span className="h-2 w-2 animate-pulse rounded-full bg-amber-400" />
                    Scoring in progress…
                  </div>
                )}
              </div>

              {/* Audit timeline */}
              <div>
                <div className="mb-2 text-xs font-medium uppercase tracking-wide text-white/50">
                  History
                </div>
                <AuditTimeline entries={data?.audit ?? []} />
              </div>

              {/* Model-teaching feedback (secondary to the state decision) */}
              <FeedbackButtons
                transactionId={txn.id}
                scored={result !== null}
                existingFeedback={data?.feedback ?? []}
                onSubmitted={load}
              />
            </>
          )}
        </div>
      </div>
    </div>
  );
}

function Fact({
  label,
  value,
  mono,
  span2,
}: {
  label: string;
  value: string;
  mono?: boolean;
  span2?: boolean;
}) {
  return (
    <div className={span2 ? "col-span-2" : ""}>
      <dt className="text-xs text-white/40">{label}</dt>
      <dd className={`mt-0.5 break-all text-white/90 ${mono ? "font-mono text-xs" : ""}`}>
        {value}
      </dd>
    </div>
  );
}
