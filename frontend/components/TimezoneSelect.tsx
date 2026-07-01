// Searchable IANA-timezone combobox: type to filter ~hundreds of zones.

"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import { allTimezones, offsetLabel } from "@/lib/timezone";

interface TimezoneSelectProps {
  value: string;
  onChange: (tz: string) => void;
  className?: string;
  buttonClassName?: string;
  placeholder?: string;
}

export function TimezoneSelect({
  value,
  onChange,
  className,
  buttonClassName,
  placeholder = "Search timezone…",
}: TimezoneSelectProps) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const rootRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const zones = useMemo(() => allTimezones(), []);
  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    const list = q
      ? zones.filter((z) => z.toLowerCase().includes(q))
      : zones;
    return list.slice(0, 200); // cap the rendered rows
  }, [zones, query]);

  // Close on outside click / Escape; focus the search box when opening.
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    inputRef.current?.focus();
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const pick = (tz: string) => {
    onChange(tz);
    setOpen(false);
    setQuery("");
  };

  return (
    <div ref={rootRef} className={`relative ${className ?? ""}`}>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className={
          buttonClassName ??
          "flex w-full items-center justify-between gap-2 rounded-md border border-white/10 bg-white/5 px-2.5 py-1.5 text-sm text-white/90 hover:border-white/25 focus:border-white/30 focus:outline-none"
        }
      >
        <span className="truncate">{value}</span>
        <span className="shrink-0 text-[10px] text-white/40">
          {offsetLabel(value)}
        </span>
      </button>

      {open && (
        <div className="absolute right-0 z-50 mt-1 w-full min-w-[15rem] overflow-hidden rounded-md border border-white/15 bg-neutral-900 shadow-xl">
          <div className="border-b border-white/10 p-2">
            <input
              ref={inputRef}
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder={placeholder}
              className="w-full rounded border border-white/10 bg-white/5 px-2 py-1 text-sm text-white/90 focus:border-white/30 focus:outline-none"
            />
          </div>
          <ul className="max-h-64 overflow-y-auto py-1">
            {filtered.length === 0 && (
              <li className="px-3 py-2 text-xs text-white/40">No matches</li>
            )}
            {filtered.map((z) => (
              <li key={z}>
                <button
                  type="button"
                  onClick={() => pick(z)}
                  className={`flex w-full items-center justify-between gap-2 px-3 py-1.5 text-left text-sm hover:bg-white/10 ${
                    z === value ? "bg-white/5 text-white" : "text-white/80"
                  }`}
                >
                  <span className="truncate">{z}</span>
                  <span className="shrink-0 text-[10px] text-white/40">
                    {offsetLabel(z)}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
