// Client-side auth session: the logged-in account, persisted to localStorage.
// This is a login GATE + identity source (it pre-fills the transaction user_id);
// the API itself is not token-protected in this demo.

"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";

import { login as apiLogin, signup as apiSignup } from "./api";

const STORAGE_KEY = "fraudshield.auth_user";

const Ctx = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [ready, setReady] = useState(false);

  // Restore a persisted session on mount (client-only, SSR-safe).
  useEffect(() => {
    try {
      const raw = window.localStorage.getItem(STORAGE_KEY);
      if (raw) setUser(JSON.parse(raw));
    } catch {
      /* ignore corrupt/absent storage */
    }
    setReady(true);
  }, []);

  const persist = useCallback((u) => {
    setUser(u);
    try {
      if (u) window.localStorage.setItem(STORAGE_KEY, JSON.stringify(u));
      else window.localStorage.removeItem(STORAGE_KEY);
    } catch {
      /* ignore storage errors */
    }
  }, []);

  const login = useCallback(
    async (email, password) => {
      persist(await apiLogin({ email, password }));
    },
    [persist],
  );

  const signup = useCallback(
    async (email, password, userId) => {
      persist(await apiSignup({ email, password, user_id: userId }));
    },
    [persist],
  );

  const logout = useCallback(() => persist(null), [persist]);

  const value = useMemo(
    () => ({ user, ready, login, signup, logout }),
    [user, ready, login, signup, logout],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAuth() {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useAuth must be used within an AuthProvider");
  return ctx;
}
