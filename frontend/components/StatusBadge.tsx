// Colored pill for a transaction's lifecycle status.

import { statusColors, statusLabel } from "@/lib/format";
import type { TransactionStatus } from "@/lib/types";

interface StatusBadgeProps {
  status: TransactionStatus;
  size?: "sm" | "md";
}

export function StatusBadge({ status, size = "md" }: StatusBadgeProps) {
  const c = statusColors(status);
  const pad = size === "sm" ? "px-1.5 py-0.5 text-[10px]" : "px-2 py-0.5 text-xs";
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-md border font-semibold ${pad} ${c.bg} ${c.border} ${c.text}`}
    >
      <span className={`h-1.5 w-1.5 rounded-full ${c.dot}`} />
      {statusLabel(status)}
    </span>
  );
}
