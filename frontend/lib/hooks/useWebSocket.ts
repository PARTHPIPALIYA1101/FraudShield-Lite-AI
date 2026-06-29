// Live feed hook for /ws/alerts: parses "transaction" events, auto-reconnects with backoff.

"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { wsAlertsUrl } from "@/lib/api";
import type { TransactionUpdateMessage } from "@/lib/types";

export type WsStatus = "connecting" | "open" | "closed";

interface UseWebSocketOptions {
  /** Called once per parsed update (in addition to being pushed into `updates`). */
  onUpdate?: (update: TransactionUpdateMessage) => void;
  /** Max updates retained in state (older ones are dropped). Default 100. */
  maxUpdates?: number;
  /** Set false to not open the socket (e.g. SSR/feature flag). Default true. */
  enabled?: boolean;
}

interface UseWebSocketResult {
  status: WsStatus;
  updates: TransactionUpdateMessage[];
  lastUpdate: TransactionUpdateMessage | null;
  clear: () => void;
}

const BASE_DELAY_MS = 1000; // first reconnect wait
const MAX_DELAY_MS = 30000; // backoff ceiling

export function useWebSocket(
  options: UseWebSocketOptions = {},
): UseWebSocketResult {
  const { onUpdate, maxUpdates = 100, enabled = true } = options;

  const [status, setStatus] = useState<WsStatus>("connecting");
  const [updates, setUpdates] = useState<TransactionUpdateMessage[]>([]);
  const [lastUpdate, setLastUpdate] = useState<TransactionUpdateMessage | null>(null);

  // Refs that must survive renders without re-triggering the connect effect.
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const attemptRef = useRef(0);
  const closedByUs = useRef(false);
  const onUpdateRef = useRef(onUpdate);
  onUpdateRef.current = onUpdate; // always current, no effect re-run

  const clear = useCallback(() => {
    setUpdates([]);
    setLastUpdate(null);
  }, []);

  useEffect(() => {
    if (!enabled) return;
    closedByUs.current = false;

    const connect = () => {
      // Don't stack sockets if one is already live/connecting.
      if (
        wsRef.current &&
        (wsRef.current.readyState === WebSocket.OPEN ||
          wsRef.current.readyState === WebSocket.CONNECTING)
      ) {
        return;
      }

      setStatus("connecting");
      let ws: WebSocket;
      try {
        ws = new WebSocket(wsAlertsUrl());
      } catch {
        scheduleReconnect();
        return;
      }
      wsRef.current = ws;

      ws.onopen = () => {
        attemptRef.current = 0; // reset backoff on a successful connect
        setStatus("open");
      };

      ws.onmessage = (event) => {
        let update: TransactionUpdateMessage;
        try {
          update = JSON.parse(event.data) as TransactionUpdateMessage;
        } catch {
          return; // ignore non-JSON / unexpected frames
        }
        if (update?.type !== "transaction") return;

        setLastUpdate(update);
        setUpdates((prev) => [update, ...prev].slice(0, maxUpdates));
        onUpdateRef.current?.(update);
      };

      ws.onerror = () => {
        // onclose will follow; let it drive the reconnect to avoid double-firing.
        ws.close();
      };

      ws.onclose = () => {
        wsRef.current = null;
        setStatus("closed");
        if (!closedByUs.current) scheduleReconnect();
      };
    };

    const scheduleReconnect = () => {
      if (closedByUs.current) return;
      const attempt = attemptRef.current++;
      // Exponential backoff with full jitter, capped at MAX_DELAY_MS.
      const expo = Math.min(BASE_DELAY_MS * 2 ** attempt, MAX_DELAY_MS);
      const delay = Math.random() * expo;
      reconnectTimer.current = setTimeout(connect, delay);
    };

    connect();

    // Teardown: stop reconnects and close the live socket cleanly.
    return () => {
      closedByUs.current = true;
      if (reconnectTimer.current) clearTimeout(reconnectTimer.current);
      reconnectTimer.current = null;
      const ws = wsRef.current;
      wsRef.current = null;
      if (ws) {
        ws.onopen = ws.onmessage = ws.onerror = ws.onclose = null;
        if (
          ws.readyState === WebSocket.OPEN ||
          ws.readyState === WebSocket.CONNECTING
        ) {
          ws.close();
        }
      }
    };
  }, [enabled, maxUpdates]);

  return { status, updates, lastUpdate, clear };
}
