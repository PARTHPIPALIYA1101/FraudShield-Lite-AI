// Vertical timeline of a transaction's state transitions (the transaction_audit ledger).

import { formatRelativeTime, statusColors, statusLabel } from "@/lib/format";
import type { AuditEntry, Actor } from "@/lib/types";

const ACTOR_LABEL: Record<Actor, string> = {
  AI: "AI",
  USER: "User",
  ANALYST: "Analyst",
  SYSTEM: "System",
};

interface AuditTimelineProps {
  entries: AuditEntry[];
}

export function AuditTimeline({ entries }: AuditTimelineProps) {
  if (entries.length === 0) {
    return <p className="text-xs text-white/40">No history yet.</p>;
  }
  return (
    <ol className="space-y-0">
      {entries.map((e, i) => {
        const c = statusColors(e.new_state);
        const last = i === entries.length - 1;
        return (
          <li key={e.id} className="flex gap-3">
            {/* rail */}
            <div className="flex flex-col items-center">
              <span className={`mt-1 h-2.5 w-2.5 shrink-0 rounded-full ${c.dot}`} />
              {!last && <span className="w-px flex-1 bg-white/10" />}
            </div>
            {/* content */}
            <div className={`pb-4 ${last ? "" : ""}`}>
              <div className="flex items-center gap-2 text-sm">
                <span className={`font-medium ${c.text}`}>
                  {statusLabel(e.new_state)}
                </span>
                <span className="text-[10px] uppercase tracking-wide text-white/40">
                  {ACTOR_LABEL[e.actor] ?? e.actor}
                  {e.actor_id ? ` · ${e.actor_id}` : ""}
                </span>
              </div>
              {e.reason && (
                <p className="mt-0.5 text-xs text-white/60">{e.reason}</p>
              )}
              <p className="mt-0.5 text-[10px] text-white/30">
                {formatRelativeTime(e.created_at)}
              </p>
            </div>
          </li>
        );
      })}
    </ol>
  );
}
