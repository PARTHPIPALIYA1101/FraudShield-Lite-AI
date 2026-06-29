// Dashboard KPI row backed by GET /stats (polled; skeleton + non-destructive error).

"use client";

import { useEffect, useRef, useState } from "react";

import { getStats } from "@/lib/api";
import { formatLatency, formatPercent } from "@/lib/format";
import type { Stats } from "@/lib/types";

const POLL_MS = 5000;

interface StatsCardsProps {
  /** Bump this to force an immediate refresh (e.g. after submitting a txn). */
  refreshKey?: number;
}

export function StatsCards({ refreshKey = 0 }: StatsCardsProps) {
  const [stats, setStats] = useState<Stats | null>(null);
  const [error, setError] = useState<string | null>(null);
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    let timer: ReturnType<typeof setTimeout>;

    const tick = async () => {
      try {
        const data = await getStats();
        if (mounted.current) {
          setStats(data);
          setError(null);
        }
      } catch {
        if (mounted.current) setError("Stats unavailable");
      } finally {
        if (mounted.current) timer = setTimeout(tick, POLL_MS);
      }
    };

    tick();
    return () => {
      mounted.current = false;
      clearTimeout(timer);
    };
  }, [refreshKey]);

  if (!stats) {
    return (
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4 lg:grid-cols-8">
        {Array.from({ length: 8 }).map((_, i) => (
          <div
            key={i}
            className="h-24 animate-pulse rounded-xl border border-white/10 bg-white/5"
          />
        ))}
      </div>
    );
  }

  const cards = [
    { label: "Today", value: String(stats.total_today), accent: "text-white" },
    { label: "Awaiting User", value: String(stats.pending_confirmation), accent: "text-amber-400" },
    { label: "Awaiting Analyst", value: String(stats.pending_review), accent: "text-sky-400" },
    { label: "Completed", value: String(stats.completed_today), accent: "text-emerald-400" },
    { label: "Declined", value: String(stats.declined_today), accent: "text-red-400" },
    { label: "Fraud Rate", value: formatPercent(stats.fraud_rate), accent: "text-orange-400" },
    { label: "Cache Hit Rate", value: formatPercent(stats.cache_hit_rate), accent: "text-emerald-400" },
    { label: "Avg Inference", value: formatLatency(stats.avg_inference_ms), accent: "text-violet-400" },
  ];

  return (
    <div className="space-y-2">
      {error && (
        <div className="rounded-md border border-amber-500/30 bg-amber-500/10 px-3 py-1.5 text-xs text-amber-300">
          {error} — showing last known values.
        </div>
      )}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4 lg:grid-cols-8">
        {cards.map((c) => (
          <div
            key={c.label}
            className="rounded-xl border border-white/10 bg-white/5 p-4 transition-colors hover:border-white/20"
          >
            <div className="text-xs font-medium uppercase tracking-wide text-white/50">
              {c.label}
            </div>
            <div className={`mt-2 text-2xl font-semibold tabular-nums ${c.accent}`}>
              {c.value}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
