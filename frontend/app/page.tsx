// The dashboard: header + KPI row + 3-pane work area (form · feed · chat) + drawer overlay.

"use client";

import { useEffect, useState } from "react";

import { AIAnalystChat } from "@/components/AIAnalystChat";
import { StatsCards } from "@/components/StatsCards";
import { TransactionDrawer } from "@/components/TransactionDrawer";
import { TransactionFeed } from "@/components/TransactionFeed";
import { TransactionForm } from "@/components/TransactionForm";
import { getHealth } from "@/lib/api";
import type { Health } from "@/lib/types";

export default function DashboardPage() {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);

  const handleSubmitted = (txnId: string) => {
    setRefreshKey((k) => k + 1); // refresh stats + feed immediately
    setSelectedId(txnId); // open the drawer to watch it get scored
  };

  return (
    <div className="flex min-h-full flex-col">
      {/* Header */}
      <header className="flex items-center justify-between border-b border-white/10 px-6 py-4">
        <div className="flex items-center gap-2.5">
          <span className="text-lg">🛡️</span>
          <h1 className="text-base font-semibold text-white/90">
            FraudShield <span className="text-white/40">Lite AI</span>
          </h1>
        </div>
        <HealthIndicator />
      </header>

      {/* Body */}
      <main className="flex flex-1 flex-col gap-5 p-6">
        <StatsCards refreshKey={refreshKey} />

        <div className="grid flex-1 grid-cols-1 gap-5 lg:grid-cols-12">
          {/* Submit */}
          <div className="lg:col-span-3">
            <TransactionForm onSubmitted={handleSubmitted} />
          </div>

          {/* Feed */}
          <div className="h-[70vh] lg:col-span-5 lg:h-auto">
            <TransactionFeed
              selectedId={selectedId}
              onSelect={setSelectedId}
              refreshKey={refreshKey}
            />
          </div>

          {/* Chat */}
          <div className="h-[70vh] lg:col-span-4 lg:h-auto">
            <AIAnalystChat contextTxnIds={selectedId ? [selectedId] : []} />
          </div>
        </div>
      </main>

      {/* Detail drawer */}
      <TransactionDrawer
        transactionId={selectedId}
        onClose={() => setSelectedId(null)}
        onActionDone={() => setRefreshKey((k) => k + 1)}
      />
    </div>
  );
}

/** Small live health dot in the header — polls /health every 10s. */
function HealthIndicator() {
  const [health, setHealth] = useState<Health | null>(null);
  const [reachable, setReachable] = useState(true);

  useEffect(() => {
    let timer: ReturnType<typeof setTimeout>;
    let on = true;
    const tick = async () => {
      try {
        const h = await getHealth();
        if (on) {
          setHealth(h);
          setReachable(true);
        }
      } catch {
        if (on) setReachable(false);
      } finally {
        if (on) timer = setTimeout(tick, 10000);
      }
    };
    tick();
    return () => {
      on = false;
      clearTimeout(timer);
    };
  }, []);

  const ok = reachable && health?.status === "ok";
  const color = !reachable ? "bg-red-400" : ok ? "bg-emerald-400" : "bg-amber-400";
  const label = !reachable ? "API offline" : ok ? "All systems healthy" : "Degraded";

  return (
    <div
      className="flex items-center gap-2 text-xs text-white/50"
      title={
        health
          ? `kafka:${health.kafka} db:${health.db} redis:${health.redis} ai:${health.anthropic_api}`
          : label
      }
    >
      <span className={`h-2 w-2 rounded-full ${color}`} />
      {label}
    </div>
  );
}
