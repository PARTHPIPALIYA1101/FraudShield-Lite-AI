// Streaming chat with the AI fraud-analyst assistant (POST /chat; per-mount session id).

"use client";

import { useEffect, useRef, useState } from "react";

import { streamChat } from "@/lib/api";

export function AIAnalystChat({ contextTxnIds = [] }) {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);

  // One session id for the lifetime of this component instance.
  const sessionId = useRef(
    typeof crypto !== "undefined" && "randomUUID" in crypto
      ? crypto.randomUUID()
      : `sess-${Math.floor(Math.random() * 1e9)}`,
  );
  const abortRef = useRef(null);
  const scrollRef = useRef(null);

  // Autoscroll to the newest content.
  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight });
  }, [messages]);

  // Cancel any in-flight stream on unmount.
  useEffect(() => () => abortRef.current?.abort(), []);

  const send = async () => {
    const text = input.trim();
    if (!text || streaming) return;

    setInput("");
    setStreaming(true);
    // Append the user turn + a placeholder assistant turn we'll fill live.
    setMessages((prev) => [
      ...prev,
      { role: "user", content: text },
      { role: "assistant", content: "" },
    ]);

    const controller = new AbortController();
    abortRef.current = controller;

    try {
      await streamChat(
        {
          session_id: sessionId.current,
          message: text,
          context_txn_ids: contextTxnIds,
        },
        (chunk) => {
          setMessages((prev) => {
            const next = [...prev];
            const last = next[next.length - 1];
            if (last?.role === "assistant") {
              next[next.length - 1] = {
                ...last,
                content: last.content + chunk,
              };
            }
            return next;
          });
        },
        controller.signal,
      );
    } catch {
      setMessages((prev) => {
        const next = [...prev];
        const last = next[next.length - 1];
        if (last?.role === "assistant" && last.content === "") {
          next[next.length - 1] = {
            ...last,
            content: "[the assistant is unavailable right now]",
          };
        }
        return next;
      });
    } finally {
      setStreaming(false);
      abortRef.current = null;
    }
  };

  const onKeyDown = (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  };

  return (
    <div className="flex h-full flex-col rounded-xl border border-white/10 bg-white/5">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-white/10 px-4 py-3">
        <h2 className="text-sm font-semibold text-white/80">AI Analyst</h2>
        {contextTxnIds.length > 0 && (
          <span className="rounded bg-sky-500/15 px-2 py-0.5 text-[10px] text-sky-300">
            {contextTxnIds.length} txn pinned
          </span>
        )}
      </div>

      {/* Messages */}
      <div ref={scrollRef} className="flex-1 space-y-3 overflow-y-auto p-4">
        {messages.length === 0 ? (
          <div className="flex h-full items-center justify-center px-6 text-center text-sm text-white/40">
            Ask about a flagged transaction, a user&apos;s pattern, or what to
            investigate next.
          </div>
        ) : (
          messages.map((m, i) => (
            <div
              key={i}
              className={m.role === "user" ? "flex justify-end" : "flex justify-start"}
            >
              <div
                className={`max-w-[85%] whitespace-pre-wrap rounded-lg px-3 py-2 text-sm ${
                  m.role === "user"
                    ? "bg-sky-500/90 text-white"
                    : "border border-white/10 bg-white/5 text-white/85"
                }`}
              >
                {m.content || (
                  <span className="inline-flex gap-1">
                    <Dot /> <Dot /> <Dot />
                  </span>
                )}
              </div>
            </div>
          ))
        )}
      </div>

      {/* Composer */}
      <div className="border-t border-white/10 p-3">
        <div className="flex items-end gap-2">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={onKeyDown}
            placeholder="Ask the AI analyst…"
            rows={1}
            className="max-h-32 flex-1 resize-none rounded-md border border-white/10 bg-white/5 px-3 py-2 text-sm text-white/90 placeholder:text-white/30 focus:border-white/30 focus:outline-none"
          />
          <button
            onClick={send}
            disabled={!input.trim() || streaming}
            className="shrink-0 rounded-md bg-sky-500/90 px-3 py-2 text-sm font-semibold text-white transition-colors hover:bg-sky-500 disabled:cursor-not-allowed disabled:opacity-40"
          >
            {streaming ? "…" : "Send"}
          </button>
        </div>
      </div>
    </div>
  );
}

function Dot() {
  return (
    <span className="inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-white/50" />
  );
}
