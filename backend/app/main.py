"""
FastAPI entry point: wires HTTP/WebSocket routes to the ingest, reconciler,
and graph_queries modules, and runs the background reconciliation loop.
"""

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.db import close_driver
from app.graph_queries import get_full_graph, get_impact, get_node_detail, neo4j_is_reachable
from app.ingest.reconciler import ensure_schema, load_cmdb_snapshot, reconcile_cycle
from app.ws_manager import manager

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

_background_task: asyncio.Task | None = None


async def _reconciliation_loop() -> None:
    """Runs forever: poll discovery + telemetry, reconcile into the graph,
    broadcast the delta. This is what makes the dashboard feel "live"
    instead of showing a one-time snapshot."""
    while True:
        try:
            delta = await reconcile_cycle()
            await manager.broadcast({"type": "graph_delta", **delta})
        except Exception:
            logger.exception("Reconciliation cycle failed; will retry next interval")
        await asyncio.sleep(settings.reconcile_interval_seconds)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _background_task
    await ensure_schema()
    await load_cmdb_snapshot()
    _background_task = asyncio.create_task(_reconciliation_loop())
    yield
    if _background_task:
        _background_task.cancel()
    await close_driver()


app = FastAPI(title="Infrastructure Knowledge Graph", lifespan=lifespan)

# Local dev only: the Vite dev server runs on a different port than uvicorn.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
async def health():
    return {"status": "ok", "neo4j_reachable": await neo4j_is_reachable()}


@app.get("/api/graph")
async def graph():
    return await get_full_graph()


@app.get("/api/nodes/{node_id}")
async def node_detail(node_id: str):
    detail = await get_node_detail(node_id)
    if detail is None:
        raise HTTPException(status_code=404, detail=f"No node with id '{node_id}'")
    return detail


@app.get("/api/impact/{node_id}")
async def impact(node_id: str):
    return await get_impact(node_id)


@app.websocket("/ws/graph-updates")
async def graph_updates(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            # We don't expect messages from the client; this just keeps the
            # connection open and lets us detect a clean disconnect.
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)
