// Global display-timezone: one selected IANA zone that every transaction time
// across the dashboard renders in. Persisted to localStorage, default IST.

"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";

import { IST_TZ } from "./geo";

const STORAGE_KEY = "fraudshield.display_tz";

const Ctx = createContext(null);

export function TimezoneProvider({ children }) {
  const [tz, setTzState] = useState(IST_TZ);

  // Hydrate from localStorage on mount (client-only to stay SSR-safe).
  useEffect(() => {
    try {
      const saved = window.localStorage.getItem(STORAGE_KEY);
      if (saved && isValidZone(saved)) setTzState(saved);
    } catch {
      /* ignore storage errors */
    }
  }, []);

  const setTz = useCallback((next) => {
    setTzState(next);
    try {
      window.localStorage.setItem(STORAGE_KEY, next);
    } catch {
      /* ignore storage errors */
    }
  }, []);

  const value = useMemo(() => ({ tz, setTz }), [tz, setTz]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

/** Access the global display timezone. Falls back to IST outside a provider. */
export function useTimezone() {
  const ctx = useContext(Ctx);
  if (!ctx) return { tz: IST_TZ, setTz: () => {} };
  return ctx;
}

/** Every IANA zone the runtime knows, with a small curated set floated to the top. */
export function allTimezones() {
  let zones = [];
  try {
    // Intl.supportedValuesOf is available in modern browsers / Node 18+.
    const sv = Intl
      .supportedValuesOf;
    if (sv) zones = sv("timeZone");
  } catch {
    /* fall through to fallback below */
  }
  if (!zones.length) {
    zones = [
      "Asia/Kolkata",
      "UTC",
      "America/New_York",
      "America/Los_Angeles",
      "Europe/London",
      "Europe/Paris",
      "Europe/Moscow",
      "Asia/Dubai",
      "Asia/Singapore",
      "Asia/Tokyo",
      "Australia/Sydney",
    ];
  }
  return zones;
}

function isValidZone(tz) {
  try {
    new Intl.DateTimeFormat("en-US", { timeZone: tz });
    return true;
  } catch {
    return false;
  }
}

/** Current UTC offset label for a zone, e.g. "GMT+5:30" — handy in a picker. */
export function offsetLabel(tz, at = new Date()) {
  try {
    const parts = new Intl.DateTimeFormat("en-US", {
      timeZone: tz,
      timeZoneName: "shortOffset",
    }).formatToParts(at);
    return parts.find((p) => p.type === "timeZoneName")?.value ?? "";
  } catch {
    return "";
  }
}
