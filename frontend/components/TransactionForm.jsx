// Submit a transaction into the pipeline (4 one-click presets + editable fields).

"use client";

import { useEffect, useState } from "react";

import { TimezoneSelect } from "@/components/TimezoneSelect";
import { ApiError, createTransaction } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { convertToUSD, CURRENCIES, currencySymbol } from "@/lib/currency";
import { formatCurrency, formatInZone } from "@/lib/format";
import { useTimezone } from "@/lib/timezone";

const PRESETS = [
  {
    label: "Normal",
    hint: "low risk → APPROVE",
    values: {
      user_id: "demo_user",
      merchant: "Starbucks",
      amount: 6.5,
      is_foreign_merchant: false,
      location: "Asia/Kolkata",
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
      location: "Europe/Paris",
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
      location: "Europe/Moscow",
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
      location: "Asia/Kolkata",
    },
  },
];

export function TransactionForm({ onSubmitted }) {
  const [form, setForm] = useState(PRESETS[0].values);
  // Amount is entered in the user's chosen currency, then converted to USD.
  const [currency, setCurrency] = useState("USD");
  const [amountInput, setAmountInput] = useState(
    String(PRESETS[0].values.amount),
  );
  const [usdPreview, setUsdPreview] = useState(
    PRESETS[0].values.amount,
  );
  const [rateError, setRateError] = useState(null);
  const [submitting, setSubmitting] = useState(false);
  const [flash, setFlash] = useState(null);
  const [error, setError] = useState(null);
  const [now, setNow] = useState(null); // set after mount (SSR-safe)

  // One shared timezone: the form's location picker and the global header
  // picker both read/write this, so changing either keeps them in sync.
  const { tz: displayTz, setTz } = useTimezone();

  // The user_id is the logged-in account's claimed handle — fixed, not editable.
  const { user } = useAuth();
  const accountUserId = user?.user_id ?? "";

  // Keep the form's user_id bound to the account (also covers a re-login switch).
  useEffect(() => {
    if (accountUserId) update("user_id", accountUserId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [accountUserId]);

  const applyPreset = (p) => {
    setForm({ ...p.values, user_id: accountUserId || p.values.user_id });
    setCurrency("USD");
    setAmountInput(String(p.values.amount));
    if (p.values.location) setTz(p.values.location); // sync the shared timezone too
    setError(null);
    setFlash(null);
  };

  const update = (
    key,
    value,
  ) => setForm((f) => ({ ...f, [key]: value }));

  // Live USD preview whenever the amount or currency changes.
  useEffect(() => {
    const n = Number(amountInput);
    if (amountInput.trim() === "" || Number.isNaN(n) || n <= 0) {
      setUsdPreview(null);
      setRateError(null);
      return;
    }
    if (currency === "USD") {
      setUsdPreview(n);
      setRateError(null);
      return;
    }
    let cancelled = false;
    convertToUSD(n, currency)
      .then((usd) => {
        if (!cancelled) {
          setUsdPreview(usd);
          setRateError(null);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setUsdPreview(null);
          setRateError("Live rate unavailable — try again.");
        }
      });
    return () => {
      cancelled = true;
    };
  }, [amountInput, currency]);

  // Tick once a second so the location clock stays synced to real time.
  useEffect(() => {
    setNow(new Date());
    const id = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(id);
  }, []);

  const submit = async () => {
    setSubmitting(true);
    setError(null);
    setFlash(null);
    try {
      const n = Number(amountInput);
      const usd = await convertToUSD(n, currency); // fresh convert avoids stale preview
      const res = await createTransaction({
        ...form,
        amount: usd,
        original_currency: currency,
        original_amount: n,
        location: displayTz, // the shared, in-sync timezone
        merchant: form.merchant.trim(),
        user_id: (accountUserId || form.user_id).trim(),
      });
      // Every submission is a distinct event now — always queued for fresh scoring.
      const origin =
        currency === "USD"
          ? ""
          : ` (${currencySymbol(currency)}${n} ${currency})`;
      setFlash(`Queued ${formatCurrency(usd)}${origin} at ${form.merchant}.`);
      onSubmitted?.(res.transaction_id);
    } catch (e) {
      if (e instanceof ApiError) setError(e.message);
      else setError(e instanceof Error ? e.message : "Submit failed.");
    } finally {
      setSubmitting(false);
    }
  };

  const amt = Number(amountInput);
  const canSubmit =
    form.user_id.trim() !== "" &&
    form.merchant.trim() !== "" &&
    amountInput.trim() !== "" &&
    !Number.isNaN(amt) &&
    amt > 0 && // a real transaction must move a positive amount
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
        <Field label="User ID (your account)">
          <input
            value={accountUserId || form.user_id}
            readOnly
            title="Taken from your signed-in account"
            className={`${inputCls} cursor-not-allowed text-white/60`}
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
          <Field label="Amount">
            <input
              type="number"
              min={0}
              step="0.01"
              value={amountInput}
              onChange={(e) => setAmountInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && canSubmit) submit();
              }}
              className={inputCls}
            />
          </Field>
          <Field label="Currency">
            <select
              value={currency}
              onChange={(e) => setCurrency(e.target.value)}
              className={inputCls}
            >
              {CURRENCIES.map((c) => (
                <option key={c.code} value={c.code} className="bg-neutral-900">
                  {c.code} · {c.label}
                </option>
              ))}
            </select>
          </Field>
        </div>

        {/* Live USD conversion preview */}
        <div className="text-xs text-white/50">
          {rateError ? (
            <span className="text-amber-400">{rateError}</span>
          ) : usdPreview != null ? (
            currency === "USD" ? (
              <>Submitted as {formatCurrency(usdPreview)}.</>
            ) : (
              <>
                ≈ <span className="text-emerald-400">{formatCurrency(usdPreview)}</span>{" "}
                at live rate — submitted in USD.
              </>
            )
          ) : (
            <>Enter an amount to see the USD equivalent.</>
          )}
        </div>

        <Field label="Location (timezone)">
          <TimezoneSelect value={displayTz} onChange={setTz} />
        </Field>

        {/* Live transaction clock in the shared timezone, synced to real time */}
        <div className="rounded-md border border-white/10 bg-white/5 px-2.5 py-2 text-[11px] leading-relaxed text-white/50">
          <div>
            Now ({displayTz}):{" "}
            <span className="text-white/80">
              {now ? formatInZone(now, displayTz) : "…"}
            </span>
          </div>
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
}) {
  return (
    <div>
      <label className="mb-1 block text-xs text-white/50">{label}</label>
      {children}
    </div>
  );
}
