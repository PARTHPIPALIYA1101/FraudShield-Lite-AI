// Display helpers + color maps shared across dashboard components.

import type { Decision, Severity, TransactionStatus } from "./types";

export function formatCurrency(amount: number): string {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 2,
  }).format(amount);
}

/** 0.1429 -> "14.3%". `digits` controls decimal places. */
export function formatPercent(fraction: number, digits = 1): string {
  return `${(fraction * 100).toFixed(digits)}%`;
}

/** 2092.7 -> "2.1s"; sub-second stays in ms. */
export function formatLatency(ms: number): string {
  if (ms >= 1000) return `${(ms / 1000).toFixed(1)}s`;
  return `${Math.round(ms)}ms`;
}

/** Format an instant in a given IANA timezone (date + time, e.g. "Jul 1, 2026, 9:05:30 PM"). */
export function formatInZone(iso: string | number | Date, tz: string): string {
  const d = iso instanceof Date ? iso : new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return new Intl.DateTimeFormat("en-US", {
    timeZone: tz,
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
    second: "2-digit",
    hour12: true,
  }).format(d);
}

/** Compact time-of-day in a zone (e.g. "9:05 PM") for dense rows. */
export function formatShortInZone(iso: string | number | Date, tz: string): string {
  const d = iso instanceof Date ? iso : new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return new Intl.DateTimeFormat("en-US", {
    timeZone: tz,
    hour: "numeric",
    minute: "2-digit",
    hour12: true,
  }).format(d);
}

/** Same instant rendered in Indian Standard Time, tagged "IST". */
export function formatIST(iso: string | number | Date): string {
  const s = formatInZone(iso, "Asia/Kolkata");
  return s ? `${s} IST` : "";
}

/** Relative time like "12s ago", "5m ago" from an ISO timestamp. */
export function formatRelativeTime(iso: string): string {
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "";
  const sec = Math.max(0, Math.round((Date.now() - then) / 1000));
  if (sec < 60) return `${sec}s ago`;
  const min = Math.round(sec / 60);
  if (min < 60) return `${min}m ago`;
  const hr = Math.round(min / 60);
  if (hr < 24) return `${hr}h ago`;
  return `${Math.round(hr / 24)}d ago`;
}

// Decision + severity -> Tailwind class fragments (text, bg, border, dot).
export interface ColorSet {
  text: string;
  bg: string;
  border: string;
  dot: string;
}

const DECISION_COLORS: Record<Decision, ColorSet> = {
  APPROVE: {
    text: "text-emerald-400",
    bg: "bg-emerald-500/10",
    border: "border-emerald-500/30",
    dot: "bg-emerald-400",
  },
  REVIEW: {
    text: "text-amber-400",
    bg: "bg-amber-500/10",
    border: "border-amber-500/30",
    dot: "bg-amber-400",
  },
  DECLINE: {
    text: "text-red-400",
    bg: "bg-red-500/10",
    border: "border-red-500/30",
    dot: "bg-red-400",
  },
};

export function decisionColors(decision: Decision): ColorSet {
  return DECISION_COLORS[decision] ?? DECISION_COLORS.REVIEW;
}

const SEVERITY_COLORS: Record<Severity, string> = {
  HIGH: "text-red-400 bg-red-500/10 border-red-500/30",
  MEDIUM: "text-amber-400 bg-amber-500/10 border-amber-500/30",
  LOW: "text-sky-400 bg-sky-500/10 border-sky-500/30",
};

export function severityClasses(severity: Severity): string {
  return SEVERITY_COLORS[severity] ?? SEVERITY_COLORS.LOW;
}

// Transaction lifecycle status -> color set + label (the PRIMARY axis for the feed/badges).
const STATUS_COLORS: Record<TransactionStatus, ColorSet> = {
  SCORING: {
    text: "text-white/60",
    bg: "bg-white/5",
    border: "border-white/15",
    dot: "bg-white/40",
  },
  COMPLETED: {
    text: "text-emerald-400",
    bg: "bg-emerald-500/10",
    border: "border-emerald-500/30",
    dot: "bg-emerald-400",
  },
  PENDING_USER_CONFIRMATION: {
    text: "text-amber-400",
    bg: "bg-amber-500/10",
    border: "border-amber-500/30",
    dot: "bg-amber-400",
  },
  PENDING_ANALYST_REVIEW: {
    text: "text-sky-400",
    bg: "bg-sky-500/10",
    border: "border-sky-500/30",
    dot: "bg-sky-400",
  },
  DECLINED: {
    text: "text-red-400",
    bg: "bg-red-500/10",
    border: "border-red-500/30",
    dot: "bg-red-400",
  },
};

const STATUS_LABELS: Record<TransactionStatus, string> = {
  SCORING: "Scoring",
  COMPLETED: "Completed",
  PENDING_USER_CONFIRMATION: "Awaiting User",
  PENDING_ANALYST_REVIEW: "Awaiting Analyst",
  DECLINED: "Declined",
};

export function statusColors(status: TransactionStatus): ColorSet {
  return STATUS_COLORS[status] ?? STATUS_COLORS.SCORING;
}

export function statusLabel(status: TransactionStatus): string {
  return STATUS_LABELS[status] ?? status;
}
