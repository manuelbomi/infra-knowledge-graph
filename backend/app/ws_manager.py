"""Tiny broadcast helper for the live graph-updates websocket - one list of connected clients, nothing fancier."""

from __future__ import annotations

import json
import logging

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ConnectionManager:
    def __init__(self) -> None:
        self._connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self._connections.append(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        if websocket in self._connections:
            self._connections.remove(websocket)

    async def broadcast(self, message: dict) -> None:
        payload = json.dumps(message, default=str)
        dead = []
        for connection in self._connections:
            try:
                await connection.send_text(payload)
            except Exception:  # noqa: BLE001 - a dead socket shouldn't break the others
                dead.append(connection)
        for connection in dead:
            self.disconnect(connection)


manager = ConnectionManager()
