// Full-screen login / signup gate shown until the user is authenticated.

"use client";

import { useState } from "react";

import { ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";

type Mode = "login" | "signup";

export function AuthScreen() {
  const { login, signup } = useAuth();
  const [mode, setMode] = useState<Mode>("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [userId, setUserId] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const isSignup = mode === "signup";

  const switchMode = (m: Mode) => {
    setMode(m);
    setError(null);
  };

  const canSubmit =
    email.trim() !== "" &&
    password !== "" &&
    (!isSignup || userId.trim() !== "") &&
    (!isSignup || password.length >= 8) &&
    !busy;

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!canSubmit) return;
    setBusy(true);
    setError(null);
    try {
      if (isSignup) await signup(email.trim(), password, userId.trim());
      else await login(email.trim(), password);
      // On success the provider sets `user`, and the gate swaps to the dashboard.
    } catch (err) {
      if (err instanceof ApiError) setError(err.message);
      else setError(err instanceof Error ? err.message : "Something went wrong.");
      setBusy(false);
    }
  };

  return (
    <div className="flex min-h-full flex-1 items-center justify-center p-6">
      <div className="w-full max-w-sm">
        <div className="mb-6 flex items-center justify-center gap-2.5">
          <span className="text-2xl">🛡️</span>
          <h1 className="text-lg font-semibold text-white/90">
            FraudShield <span className="text-white/40">Lite AI</span>
          </h1>
        </div>

        <div className="rounded-xl border border-white/10 bg-white/5 p-5">
          {/* Tab switch */}
          <div className="mb-5 grid grid-cols-2 gap-1 rounded-lg bg-white/5 p-1 text-sm">
            <button
              type="button"
              onClick={() => switchMode("login")}
              className={`rounded-md py-1.5 font-medium transition-colors ${
                !isSignup ? "bg-white/10 text-white" : "text-white/50 hover:text-white/80"
              }`}
            >
              Sign in
            </button>
            <button
              type="button"
              onClick={() => switchMode("signup")}
              className={`rounded-md py-1.5 font-medium transition-colors ${
                isSignup ? "bg-white/10 text-white" : "text-white/50 hover:text-white/80"
              }`}
            >
              Sign up
            </button>
          </div>

          <form onSubmit={submit} className="space-y-3">
            <Field label="Email">
              <input
                type="email"
                autoComplete="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className={inputCls}
                placeholder="you@example.com"
              />
            </Field>

            {isSignup && (
              <Field label="User ID (unique — claim your handle)">
                <input
                  value={userId}
                  onChange={(e) => setUserId(e.target.value)}
                  className={inputCls}
                  placeholder="parth_01"
                  maxLength={50}
                />
              </Field>
            )}

            <Field label="Password">
              <input
                type="password"
                autoComplete={isSignup ? "new-password" : "current-password"}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className={inputCls}
                placeholder={isSignup ? "at least 8 characters" : "••••••••"}
              />
            </Field>

            {error && <p className="text-xs text-amber-400">{error}</p>}

            <button
              type="submit"
              disabled={!canSubmit}
              className="w-full rounded-md bg-sky-500/90 px-3 py-2 text-sm font-semibold text-white transition-colors hover:bg-sky-500 disabled:cursor-not-allowed disabled:opacity-40"
            >
              {busy
                ? isSignup
                  ? "Creating account…"
                  : "Signing in…"
                : isSignup
                  ? "Create account"
                  : "Sign in"}
            </button>
          </form>

          <p className="mt-4 text-center text-xs text-white/40">
            {isSignup ? (
              <>
                Already have an account?{" "}
                <button
                  type="button"
                  onClick={() => switchMode("login")}
                  className="text-sky-400 hover:underline"
                >
                  Sign in
                </button>
              </>
            ) : (
              <>
                No account?{" "}
                <button
                  type="button"
                  onClick={() => switchMode("signup")}
                  className="text-sky-400 hover:underline"
                >
                  Sign up
                </button>
              </>
            )}
          </p>
        </div>
      </div>
    </div>
  );
}

const inputCls =
  "w-full rounded-md border border-white/10 bg-white/5 px-2.5 py-1.5 text-sm text-white/90 focus:border-white/30 focus:outline-none";

function Field({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <label className="mb-1 block text-xs text-white/50">{label}</label>
      {children}
    </div>
  );
}
