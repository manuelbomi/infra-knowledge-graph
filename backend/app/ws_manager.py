"""
Tracks connected WebSocket clients and broadcasts graph deltas to all of them.

Deliberately simple (a list in process memory) because this app runs as a
single process. Scaling this to multiple backend instances would need a
pub/sub layer (Redis, NATS, etc.) so a delta produced on one instance reaches
clients connected to another -- called out in the README.
"""

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
        payload = json.dumps(message)
        dead_connections = []
        for connection in self._connections:
            try:
                await connection.send_text(payload)
            except Exception:
                dead_connections.append(connection)
        for connection in dead_connections:
            self.disconnect(connection)


manager = ConnectionManager()
