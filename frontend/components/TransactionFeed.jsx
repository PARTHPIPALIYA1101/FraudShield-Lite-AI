// Live transaction list: REST poll + WS updates merged by id; primary axis = status.

"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { listTransactions } from "@/lib/api";
import { decisionColors, formatCurrency, formatInZone, formatRelativeTime, formatShortInZone, statusColors, statusLabel } from "@/lib/format";
import { useWebSocket } from "@/lib/hooks/useWebSocket";
import { useTimezone } from "@/lib/timezone";

function fromRest(t) {
  return {
    id: t.transaction.id,
    user_id: t.transaction.user_id,
    merchant: t.transaction.merchant,
    amount: t.transaction.amount,
    is_foreign_merchant: t.transaction.is_foreign_merchant,
    ts: t.transaction.created_at,
    status: t.transaction.status,
    recommendation: t.fraud_result?.decision ?? null,
    fraud_score: t.fraud_result?.fraud_score ?? null,
  };
}

function fromUpdate(u) {
  return {
    id: u.transaction.id,
    user_id: u.transaction.user_id,
    merchant: u.transaction.merchant,
    amount: u.transaction.amount,
    is_foreign_merchant: u.transaction.is_foreign_merchant,
    ts: u.transaction.timestamp,
    status: u.status,
    recommendation: u.fraud_result?.decision ?? null,
    fraud_score: u.fraud_result?.fraud_score ?? null,
  };
}

const STATUS_FILTERS = [
  { label: "All", value: "ALL" },
  { label: "Awaiting User", value: "PENDING_USER_CONFIRMATION" },
  { label: "Awaiting Analyst", value: "PENDING_ANALYST_REVIEW" },
  { label: "Completed", value: "COMPLETED" },
  { label: "Declined", value: "DECLINED" },
];

const POLL_MS = 5000;
const PAGE_LIMIT = 50;

export function TransactionFeed({
  selectedId,
  onSelect,
  refreshKey = 0,
}) {
  // Map id -> item is the source of truth; render derives a sorted array.
  const [itemsById, setItemsById] = useState(new Map());
  const [filter, setFilter] = useState("ALL");
  const [loading, setLoading] = useState(true); // until the first poll resolves
  const [error, setError] = useState(false); // last poll failed (stale data shown)
  const { tz } = useTimezone();
  const mounted = useRef(true);

  const mergeItems = useCallback((incoming) => {
    setItemsById((prev) => {
      const next = new Map(prev);
      for (const item of incoming) {
        const existing = next.get(item.id);
        // Latest status wins; keep recommendation/score sticky if absent.
        next.set(item.id, {
          ...existing,
          ...item,
          recommendation: item.recommendation ?? existing?.recommendation ?? null,
          fraud_score: item.fraud_score ?? existing?.fraud_score ?? null,
        });
      }
      return next;
    });
  }, []);

  // --- WS: reflect every transition the instant it happens ---
  useWebSocket({
    onUpdate: useCallback(
      (u) => mergeItems([fromUpdate(u)]),
      [mergeItems],
    ),
  });

  // --- REST poll: full, self-healing picture ---
  useEffect(() => {
    mounted.current = true;
    let timer;

    const tick = async () => {
      try {
        const data = await listTransactions({ limit: PAGE_LIMIT });
        if (mounted.current) {
          mergeItems(data.items.map(fromRest));
          setError(false);
        }
      } catch {
        if (mounted.current) setError(true); // keep showing stale rows
      } finally {
        if (mounted.current) {
          setLoading(false);
          timer = setTimeout(tick, POLL_MS);
        }
      }
    };

    tick();
    return () => {
      mounted.current = false;
      clearTimeout(timer);
    };
  }, [mergeItems, refreshKey]);

  const rows = useMemo(() => {
    let list = Array.from(itemsById.values());
    if (filter !== "ALL") list = list.filter((r) => r.status === filter);
    return list.sort((a, b) => new Date(b.ts).getTime() - new Date(a.ts).getTime());
  }, [itemsById, filter]);

  return (
    <div className="flex h-full flex-col rounded-xl border border-white/10 bg-white/5">
      {/* Header + filter */}
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-white/10 px-4 py-3">
        <div className="flex items-center gap-2">
          <h2 className="text-sm font-semibold text-white/80">Live Transactions</h2>
          {error && (
            <span
              className="rounded bg-amber-500/15 px-1.5 py-0.5 text-[10px] text-amber-300"
              title="The feed could not refresh — showing the last known data."
            >
              stale
            </span>
          )}
        </div>
        <div className="flex flex-wrap gap-1">
          {STATUS_FILTERS.map((f) => (
            <button
              key={f.value}
              onClick={() => setFilter(f.value)}
              className={`rounded-md px-2 py-1 text-xs font-medium transition-colors ${
                filter === f.value
                  ? "bg-white/15 text-white"
                  : "text-white/50 hover:bg-white/5 hover:text-white/80"
              }`}
            >
              {f.label}
            </button>
          ))}
        </div>
      </div>

      {/* List */}
      <div className="flex-1 overflow-y-auto">
        {loading && rows.length === 0 ? (
          <ul className="divide-y divide-white/5">
            {Array.from({ length: 6 }).map((_, i) => (
              <li key={i} className="flex items-center gap-3 px-4 py-3">
                <span className="h-2 w-2 shrink-0 rounded-full bg-white/10" />
                <div className="flex-1 space-y-1.5">
                  <div className="h-3 w-32 animate-pulse rounded bg-white/10" />
                  <div className="h-2.5 w-20 animate-pulse rounded bg-white/5" />
                </div>
                <div className="h-3 w-14 animate-pulse rounded bg-white/10" />
              </li>
            ))}
          </ul>
        ) : rows.length === 0 ? (
          <div className="flex h-full items-center justify-center p-8 text-sm text-white/40">
            No transactions yet — submit one to see it scored live.
          </div>
        ) : (
          <ul className="divide-y divide-white/5">
            {rows.map((r) => {
              const sc = statusColors(r.status);
              const rc = r.recommendation ? decisionColors(r.recommendation) : null;
              const selected = r.id === selectedId;
              return (
                <li key={r.id}>
                  <button
                    onClick={() => onSelect?.(r.id)}
                    className={`flex w-full items-center gap-3 px-4 py-3 text-left transition-colors ${
                      selected ? "bg-white/10" : "hover:bg-white/5"
                    }`}
                  >
                    {/* status dot */}
                    <span className={`h-2 w-2 shrink-0 rounded-full ${sc.dot}`} />
                    {/* merchant + user */}
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <span className="truncate text-sm font-medium text-white/90">
                          {r.merchant}
                        </span>
                        {r.is_foreign_merchant && (
                          <span className="shrink-0 rounded bg-white/10 px-1 text-[10px] text-white/50">
                            foreign
                          </span>
                        )}
                      </div>
                      <div
                        className="truncate text-xs text-white/40"
                        title={formatInZone(r.ts, tz)}
                      >
                        {r.user_id} · {formatRelativeTime(r.ts)} ·{" "}
                        {formatShortInZone(r.ts, tz)}
                      </div>
                    </div>
                    {/* amount + status (primary) + AI rec (secondary) */}
                    <div className="shrink-0 text-right">
                      <div className="text-sm font-medium tabular-nums text-white/90">
                        {formatCurrency(r.amount)}
                      </div>
                      <div className={`text-xs font-medium ${sc.text}`}>
                        {statusLabel(r.status)}
                      </div>
                      {rc && (
                        <div className="text-[10px] text-white/40">
                          AI: <span className={rc.text}>{r.recommendation}</span>
                          {r.fraud_score != null ? ` ${r.fraud_score.toFixed(2)}` : ""}
                        </div>
                      )}
                    </div>
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </div>
  );
}
