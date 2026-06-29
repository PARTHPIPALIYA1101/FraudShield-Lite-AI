"""Fan-out hub for the live /ws/alerts feed."""

import asyncio
import logging
from typing import Any

from fastapi import WebSocket

logger = logging.getLogger("fraudshield.ws")


class ConnectionManager:
    """Tracks live subscribers and fans out messages to all of them."""

    def __init__(self) -> None:
        self._connections: set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket) -> None:
        """Accept the handshake and register the client."""
        await websocket.accept()
        async with self._lock:
            self._connections.add(websocket)
        logger.info("WS client connected (%d total)", len(self._connections))

    async def disconnect(self, websocket: WebSocket) -> None:
        """Deregister a client (idempotent)."""
        async with self._lock:
            self._connections.discard(websocket)
        logger.info("WS client disconnected (%d total)", len(self._connections))

    async def broadcast(self, message: dict[str, Any]) -> None:
        """Send `message` (JSON) to every client; prune any that error."""
        async with self._lock:
            if not self._connections:
                return
            dead: list[WebSocket] = []
            for ws in list(self._connections):
                try:
                    await ws.send_json(message)
                except Exception as exc:  # noqa: BLE001 — any send failure -> prune
                    logger.warning("WS send failed, pruning client: %s", exc)
                    dead.append(ws)
            for ws in dead:
                self._connections.discard(ws)

    @property
    def count(self) -> int:
        """Current number of live subscribers."""
        return len(self._connections)


# Process-wide singleton imported by main (the WS route) and the consumer.
manager = ConnectionManager()
