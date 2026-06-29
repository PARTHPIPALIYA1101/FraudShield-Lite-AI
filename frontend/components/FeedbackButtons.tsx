// Analyst labels a scored txn (CONFIRMED_FRAUD / FALSE_POSITIVE) -> the no-retraining loop.

"use client";

import { useState } from "react";

import { ApiError, submitFeedback } from "@/lib/api";
import type { AnalystLabel, Feedback } from "@/lib/types";

interface FeedbackButtonsProps {
  transactionId: string;
  /** Whether the txn has a fraud_result yet — feedback requires one (FK NOT NULL). */
  scored: boolean;
  existingFeedback?: Feedback[];
  onSubmitted?: () => void;
}

export function FeedbackButtons({
  transactionId,
  scored,
  existingFeedback = [],
  onSubmitted,
}: FeedbackButtonsProps) {
  const [notes, setNotes] = useState("");
  const [submitting, setSubmitting] = useState<AnalystLabel | null>(null);
  const [done, setDone] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const send = async (label: AnalystLabel) => {
    setSubmitting(label);
    setError(null);
    try {
      await submitFeedback({
        transaction_id: transactionId,
        label,
        notes: notes.trim() || null,
      });
      setDone(true);
      setNotes("");
      onSubmitted?.();
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) {
        setError("Not scored yet — try again in a moment.");
      } else {
        setError(e instanceof Error ? e.message : "Failed to submit feedback.");
      }
    } finally {
      setSubmitting(null);
    }
  };

  const labelText: Record<AnalystLabel, string> = {
    CONFIRMED_FRAUD: "Confirmed Fraud",
    FALSE_POSITIVE: "False Positive",
  };

  return (
    <div className="space-y-3">
      <div className="text-xs font-medium uppercase tracking-wide text-white/50">
        Analyst Feedback
      </div>

      {/* Existing labels */}
      {existingFeedback.length > 0 && (
        <ul className="space-y-1">
          {existingFeedback.map((f) => (
            <li
              key={f.id}
              className="rounded-md border border-white/10 bg-white/5 px-2.5 py-1.5 text-xs"
            >
              <span
                className={
                  f.analyst_label === "CONFIRMED_FRAUD"
                    ? "font-semibold text-red-400"
                    : "font-semibold text-emerald-400"
                }
              >
                {labelText[f.analyst_label]}
              </span>
              {f.analyst_notes && (
                <span className="text-white/60"> — {f.analyst_notes}</span>
              )}
            </li>
          ))}
        </ul>
      )}

      {done ? (
        <div className="rounded-md border border-emerald-500/30 bg-emerald-500/10 px-3 py-2 text-xs text-emerald-300">
          Feedback recorded — it will shape future scoring for this user.
        </div>
      ) : (
        <>
          <textarea
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            placeholder="Optional notes (e.g. customer confirmed the charge)…"
            rows={2}
            disabled={!scored}
            className="w-full resize-none rounded-md border border-white/10 bg-white/5 px-2.5 py-2 text-sm text-white/90 placeholder:text-white/30 focus:border-white/30 focus:outline-none disabled:opacity-50"
          />
          <div className="flex gap-2">
            <button
              onClick={() => send("CONFIRMED_FRAUD")}
              disabled={!scored || submitting !== null}
              className="flex-1 rounded-md border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm font-medium text-red-300 transition-colors hover:bg-red-500/20 disabled:cursor-not-allowed disabled:opacity-40"
            >
              {submitting === "CONFIRMED_FRAUD" ? "Saving…" : "Confirm Fraud"}
            </button>
            <button
              onClick={() => send("FALSE_POSITIVE")}
              disabled={!scored || submitting !== null}
              className="flex-1 rounded-md border border-emerald-500/30 bg-emerald-500/10 px-3 py-2 text-sm font-medium text-emerald-300 transition-colors hover:bg-emerald-500/20 disabled:cursor-not-allowed disabled:opacity-40"
            >
              {submitting === "FALSE_POSITIVE" ? "Saving…" : "False Positive"}
            </button>
          </div>
          {!scored && (
            <p className="text-xs text-white/40">
              Awaiting AI assessment before feedback can be recorded.
            </p>
          )}
          {error && <p className="text-xs text-amber-400">{error}</p>}
        </>
      )}
    </div>
  );
}
