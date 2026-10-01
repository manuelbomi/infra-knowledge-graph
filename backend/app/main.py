"""
FastAPI app. Serves the reconciled graph from the in-memory
ReconciliationEngine (see app/reconciliation/engine.py for why), runs the
ingestion adapters on a background loop, mirrors state into Neo4j when it's
available, and pushes live deltas to any connected dashboard over a
websocket.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.graph.neo4j_sync import ensure_constraints, sync_graph
from app.ingest.orchestrator import IngestionOrchestrator
from app.ontology.schema import NodeLabel
from app.reconciliation.engine import ReconciliationEngine
from app.reconciliation.models import ChangeEvent
from app.ws_manager import manager

app = FastAPI(title="Infrastructure Knowledge Graph", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

engine = ReconciliationEngine()
orchestrator = IngestionOrchestrator(engine)
_background_task: asyncio.Task | None = None


def _health_of(node) -> str | None:
    """
    Collapses status + staleness into the three-value health the dashboard
    draws a ring for. Only Host nodes carry telemetry in this project, so
    everything else gets no health ring at all (None), which the frontend
    already treats as "no ring" - see colors.ts HEALTH_RING_COLOR.
    """
    if node.label != NodeLabel.HOST:
        return None
    stale_ids = engine.stale_host_ids(datetime.now(UTC), settings.staleness_ttl_seconds)
    if node.node_id in stale_ids:
        return "unknown (no recent heartbeat)"
    status = node.properties.get("status")
    if status is None:
        return None
    return "healthy" if status == "healthy" else "unhealthy"


async def _on_change(events: list[ChangeEvent]) -> None:
    await sync_graph(engine)

    updated_nodes = []
    new_incidents = []
    incident_affects: dict[str, str] = {}

    # AFFECTS edges and their IncidentEvent node both land in the same
    # batch of events (telemetry_adapter emits them together) - correlate
    # them here so the dashboard gets one clean "new_incidents" entry
    # instead of having to piece it together from two separate updates.
    for event in events:
        if event.kind == "edge_upserted" and event.detail["rel_type"] == "AFFECTS":
            incident_affects[event.detail["from_id"]] = event.detail["to_id"]

    for event in events:
        if event.kind != "node_upserted":
            continue
        label = event.detail["label"]
        node_id = event.detail["node_id"]
        if label == NodeLabel.INCIDENT_EVENT.value:
            new_incidents.append(
                {
                    "id": node_id,
                    "affects": incident_affects.get(node_id),
                    "started_at": event.detail["properties"].get("started_at"),
                }
            )
            continue
        node = engine.nodes.get((label, node_id))
        updated_nodes.append({"id": node_id, "label": label, "health": _health_of(node) if node else None})

    updated_edges = []
    removed_edges = []
    for event in events:
        if event.kind == "edge_upserted":
            updated_edges.append(
                {"from": event.detail["from_id"], "to": event.detail["to_id"], "rel_type": event.detail["rel_type"]}
            )
        elif event.kind == "edge_removed":
            removed_edges.append(
                {"from": event.detail["from_id"], "to": event.detail["to_id"], "rel_type": event.detail["rel_type"]}
            )

    await manager.broadcast(
        {
            "type": "graph_delta",
            "timestamp": datetime.now(UTC).isoformat(),
            "updated_nodes": updated_nodes,
            "updated_edges": updated_edges,
            "removed_edges": removed_edges,
            "new_incidents": [i for i in new_incidents if i["affects"] is not None],
        }
    )


@app.on_event("startup")
async def startup() -> None:
    global _background_task
    # Run one tick synchronously so the API has data to serve immediately,
    # then hand off to the background loop for everything after.
    orchestrator.run_once()
    await sync_graph(engine)
    _background_task = asyncio.create_task(
        orchestrator.run_forever(settings.reconcile_interval_seconds, _on_change)
    )


def _node_to_graph_dict(node) -> dict:
    d = {"id": node.node_id, "label": node.label.value, **node.properties}
    health = _health_of(node)
    if health is not None:
        d["health"] = health
    return d


def _edge_to_graph_dict(edge) -> dict:
    return {"source": edge.from_id, "target": edge.to_id, "rel_type": edge.rel_type.value, "source_label": edge.source}


@app.get("/api/health")
async def health() -> dict:
    return {"status": "ok", "neo4j_reachable": await ensure_constraints(), "tick_count": orchestrator.tick_count}


@app.get("/api/graph")
def get_graph() -> dict:
    return {
        "nodes": [_node_to_graph_dict(n) for n in engine.all_nodes()],
        "edges": [_edge_to_graph_dict(e) for e in engine.all_active_edges()],
    }


@app.get("/api/nodes/{node_id}")
def get_node(node_id: str) -> dict:
    label_value = engine.label_of(node_id)
    if label_value is None:
        raise HTTPException(status_code=404, detail="node not found")
    node = engine.nodes[(label_value, node_id)]

    outgoing = []
    incoming = []
    for (rel_type, from_id, to_id), edge in engine.edges.items():
        if not edge.active:
            continue
        if from_id == node_id:
            outgoing.append(
                {
                    "rel_type": rel_type,
                    "target_id": to_id,
                    "target_label": engine.label_of(to_id),
                    "props": {"source": edge.source, "last_confirmed_at": edge.last_confirmed_at.isoformat()},
                }
            )
        if to_id == node_id:
            incoming.append(
                {
                    "rel_type": rel_type,
                    "source_id": from_id,
                    "source_label": engine.label_of(from_id),
                    "props": {"source": edge.source, "last_confirmed_at": edge.last_confirmed_at.isoformat()},
                }
            )

    return {
        "id": node_id,
        "label": label_value,
        "properties": dict(node.properties),
        "outgoing_relationships": outgoing,
        "incoming_relationships": incoming,
    }


@app.get("/api/impact/{node_id}")
def get_impact(node_id: str) -> dict:
    label_value = engine.label_of(node_id)
    if label_value is None:
        raise HTTPException(status_code=404, detail="node not found")
    label = NodeLabel(label_value)
    return {
        "node_id": node_id,
        "downstream_impact": engine.impact(label, node_id),
        "upstream_dependencies": engine.dependencies(label, node_id),
    }


@app.get("/api/metrics")
def get_metrics() -> dict:
    nodes = engine.all_nodes()
    edges = engine.all_active_edges()
    by_label: dict[str, int] = {}
    for node in nodes:
        by_label[node.label.value] = by_label.get(node.label.value, 0) + 1
    stale_count = len(engine.stale_host_ids(datetime.now(UTC), settings.staleness_ttl_seconds))
    return {
        "node_counts_by_label": by_label,
        "total_edges": len(edges),
        "stale_host_count": stale_count,
        "tick_count": orchestrator.tick_count,
    }


@app.websocket("/ws/graph-updates")
async def graph_updates(websocket: WebSocket) -> None:
    await manager.connect(websocket)
    try:
        while True:
            # The dashboard doesn't need to send anything - this just keeps
            # the connection open and lets us detect disconnects.
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)
