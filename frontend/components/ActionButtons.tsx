// Status-driven decision controls (confirm/cancel for user, approve/reject for analyst).

"use client";

import { useState } from "react";

import {
  ApiError,
  approveTransaction,
  cancelTransaction,
  confirmTransaction,
  rejectTransaction,
} from "@/lib/api";
import type { TransactionStatus } from "@/lib/types";

interface ActionButtonsProps {
  transactionId: string;
  status: TransactionStatus;
  onActionDone?: () => void;
}

export function ActionButtons({
  transactionId,
  status,
  onActionDone,
}: ActionButtonsProps) {
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const run = async (
    action: "confirm" | "cancel" | "approve" | "reject",
    fn: () => Promise<unknown>,
  ) => {
    setBusy(action);
    setError(null);
    try {
      await fn();
      onActionDone?.();
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) {
        setError("This transaction already moved on — refreshing.");
        onActionDone?.(); // re-sync to the real state
      } else {
        setError(e instanceof Error ? e.message : "Action failed.");
      }
    } finally {
      setBusy(null);
    }
  };

  if (status === "PENDING_USER_CONFIRMATION") {
    return (
      <Wrapper error={error}>
        <button
          onClick={() => run("cancel", () => cancelTransaction(transactionId))}
          disabled={busy !== null}
          className={btn("danger")}
        >
          {busy === "cancel" ? "Cancelling…" : "Cancel Transaction"}
        </button>
        <button
          onClick={() => run("confirm", () => confirmTransaction(transactionId))}
          disabled={busy !== null}
          className={btn("warn")}
        >
          {busy === "confirm" ? "Submitting…" : "Continue Anyway"}
        </button>
      </Wrapper>
    );
  }

  if (status === "PENDING_ANALYST_REVIEW") {
    return (
      <Wrapper error={error}>
        <button
          onClick={() => run("reject", () => rejectTransaction(transactionId))}
          disabled={busy !== null}
          className={btn("danger")}
        >
          {busy === "reject" ? "Rejecting…" : "Reject Transaction"}
        </button>
        <button
          onClick={() => run("approve", () => approveTransaction(transactionId))}
          disabled={busy !== null}
          className={btn("success")}
        >
          {busy === "approve" ? "Approving…" : "Approve Transaction"}
        </button>
      </Wrapper>
    );
  }

  // Terminal or still scoring — nothing to act on.
  const note =
    status === "SCORING"
      ? "Awaiting AI assessment…"
      : status === "COMPLETED"
        ? "Payment completed — no further action."
        : "Payment declined — no further action.";
  return <p className="text-xs text-white/40">{note}</p>;
}

function Wrapper({
  children,
  error,
}: {
  children: React.ReactNode;
  error: string | null;
}) {
  return (
    <div className="space-y-2">
      <div className="flex gap-2">{children}</div>
      {error && <p className="text-xs text-amber-400">{error}</p>}
    </div>
  );
}

function btn(kind: "success" | "danger" | "warn"): string {
  const base =
    "flex-1 rounded-md border px-3 py-2 text-sm font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-40";
  const variants = {
    success:
      "border-emerald-500/30 bg-emerald-500/10 text-emerald-300 hover:bg-emerald-500/20",
    danger: "border-red-500/30 bg-red-500/10 text-red-300 hover:bg-red-500/20",
    warn: "border-amber-500/30 bg-amber-500/10 text-amber-300 hover:bg-amber-500/20",
  };
  return `${base} ${variants[kind]}`;
}
