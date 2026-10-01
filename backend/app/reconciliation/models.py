"""
The shapes an ingestion adapter hands to the reconciliation engine.

An adapter never writes to the graph directly. Instead it reports what it
observed, as one of these two types, and the engine decides what to do about
it (see engine.py). That separation is what lets three sources disagree
without stepping on each other - a `NodeObservation` from the CMDB and one
from telemetry about the same host are just two inputs the engine has to
reconcile, not two writes racing each other.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from app.ontology.schema import NodeLabel, RelType


@dataclass
class NodeObservation:
    label: NodeLabel
    node_id: str
    properties: dict
    source: str
    observed_at: datetime


@dataclass
class EdgeObservation:
    rel_type: RelType
    from_id: str
    to_id: str
    source: str
    observed_at: datetime
    # False means "this source actively checked and the edge is gone now"
    # (used by the discovery adapter when a dependency disappears), as
    # opposed to simply not being mentioned in this tick.
    present: bool = True
    properties: dict = field(default_factory=dict)


@dataclass
class ChangeEvent:
    """One line of 'what just happened', used for the audit trail and pushed over the websocket as a live delta."""

    kind: str  # "node_upserted" | "node_field_changed" | "edge_upserted" | "edge_removed" | "node_stale"
    timestamp: datetime
    detail: dict
