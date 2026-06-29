// Submit a transaction into the pipeline (4 one-click presets + editable fields).

"use client";

import { useState } from "react";

import { ApiError, createTransaction } from "@/lib/api";
import { formatCurrency } from "@/lib/format";
import type { TransactionCreate } from "@/lib/types";

interface Preset {
  label: string;
  hint: string;
  values: TransactionCreate;
}

const PRESETS: Preset[] = [
  {
    label: "Normal",
    hint: "low risk → APPROVE",
    values: {
      user_id: "demo_user",
      merchant: "Starbucks",
      amount: 6.5,
      is_foreign_merchant: false,
      location: "Mumbai, IN",
    },
  },
  {
    label: "Foreign High",
    hint: "big + foreign → DECLINE",
    values: {
      user_id: "demo_user",
      merchant: "LuxuryWatchesParis",
      amount: 8500,
      is_foreign_merchant: true,
      location: "Paris, FR",
    },
  },
  {
    label: "Risky Merchant",
    hint: "new + foreign → DECLINE",
    values: {
      user_id: "demo_user",
      merchant: "DarkBazaarRU",
      amount: 4200,
      is_foreign_merchant: true,
      location: "Moscow, RU",
    },
  },
  {
    label: "Velocity",
    hint: "submit repeatedly → REVIEW",
    values: {
      user_id: "burst_user",
      merchant: "OnlineGameStore",
      amount: 320,
      is_foreign_merchant: false,
      location: "Delhi, IN",
    },
  },
];

interface TransactionFormProps {
  onSubmitted?: (transactionId: string) => void;
}

export function TransactionForm({ onSubmitted }: TransactionFormProps) {
  const [form, setForm] = useState<TransactionCreate>(PRESETS[0].values);
  const [submitting, setSubmitting] = useState(false);
  const [flash, setFlash] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const applyPreset = (p: Preset) => {
    setForm(p.values);
    setError(null);
    setFlash(null);
  };

  const update = <K extends keyof TransactionCreate>(
    key: K,
    value: TransactionCreate[K],
  ) => setForm((f) => ({ ...f, [key]: value }));

  const submit = async () => {
    setSubmitting(true);
    setError(null);
    setFlash(null);
    try {
      const res = await createTransaction({
        ...form,
        merchant: form.merchant.trim(),
        user_id: form.user_id.trim(),
      });
      // Every submission is a distinct event now — always queued for fresh scoring.
      setFlash(`Queued ${formatCurrency(form.amount)} at ${form.merchant}.`);
      onSubmitted?.(res.transaction_id);
    } catch (e) {
      if (e instanceof ApiError) setError(e.message);
      else setError(e instanceof Error ? e.message : "Submit failed.");
    } finally {
      setSubmitting(false);
    }
  };

  const canSubmit =
    form.user_id.trim() !== "" &&
    form.merchant.trim() !== "" &&
    form.amount >= 0 &&
    !submitting;

  return (
    <div className="rounded-xl border border-white/10 bg-white/5 p-4">
      <h2 className="text-sm font-semibold text-white/80">Submit Transaction</h2>

      {/* Presets */}
      <div className="mt-3 grid grid-cols-2 gap-2">
        {PRESETS.map((p) => (
          <button
            key={p.label}
            onClick={() => applyPreset(p)}
            className="rounded-md border border-white/10 bg-white/5 px-2.5 py-2 text-left transition-colors hover:border-white/25 hover:bg-white/10"
          >
            <div className="text-xs font-medium text-white/90">{p.label}</div>
            <div className="text-[10px] text-white/40">{p.hint}</div>
          </button>
        ))}
      </div>

      {/* Fields */}
      <div className="mt-4 space-y-3">
        <Field label="User ID">
          <input
            value={form.user_id}
            onChange={(e) => update("user_id", e.target.value)}
            className={inputCls}
          />
        </Field>
        <Field label="Merchant">
          <input
            value={form.merchant}
            onChange={(e) => update("merchant", e.target.value)}
            className={inputCls}
          />
        </Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Amount (USD)">
            <input
              type="number"
              min={0}
              step="0.01"
              value={form.amount}
              onChange={(e) => update("amount", Number(e.target.value))}
              className={inputCls}
            />
          </Field>
          <Field label="Location">
            <input
              value={form.location ?? ""}
              onChange={(e) => update("location", e.target.value)}
              className={inputCls}
            />
          </Field>
        </div>
        <label className="flex items-center gap-2 text-sm text-white/70">
          <input
            type="checkbox"
            checked={form.is_foreign_merchant ?? false}
            onChange={(e) => update("is_foreign_merchant", e.target.checked)}
            className="h-4 w-4 rounded border-white/20 bg-white/5"
          />
          Foreign merchant
        </label>
      </div>

      {/* Submit + status */}
      <button
        onClick={submit}
        disabled={!canSubmit}
        className="mt-4 w-full rounded-md bg-sky-500/90 px-3 py-2 text-sm font-semibold text-white transition-colors hover:bg-sky-500 disabled:cursor-not-allowed disabled:opacity-40"
      >
        {submitting ? "Submitting…" : "Submit Transaction"}
      </button>
      {flash && <p className="mt-2 text-xs text-emerald-400">{flash}</p>}
      {error && <p className="mt-2 text-xs text-amber-400">{error}</p>}
    </div>
  );
}

const inputCls =
  "w-full rounded-md border border-white/10 bg-white/5 px-2.5 py-1.5 text-sm text-white/90 focus:border-white/30 focus:outline-none";

function Field({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <label className="mb-1 block text-xs text-white/50">{label}</label>
      {children}
    </div>
  );
}
