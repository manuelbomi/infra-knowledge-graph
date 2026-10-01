"""
The reconciliation engine: the one place that holds "what we currently
believe the graph looks like", built up from whatever observations the
ingestion adapters report.

This is deliberately plain Python with no Neo4j import anywhere in this
file. That's what makes it possible to unit test every conflict-resolution
and blast-radius rule without a database running - see tests/test_reconciliation.py
and tests/test_impact.py. Neo4j is still used for real (see
app/graph/neo4j_sync.py) as the durable, Cypher-queryable copy of this same
state - this class is the fast, authoritative in-memory view the API and
websocket serve from, kept in sync with Neo4j rather than replaced by it.
See the README for why this split makes sense at this project's scale, and
what changes if it needs to run as more than one process.
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime

from app.ontology.schema import NodeLabel, REQUIRES_REL_TYPES, RelType, validate_node_properties

from .models import ChangeEvent, EdgeObservation, NodeObservation
from .trust import field_owner_rule


@dataclass
class NodeState:
    label: NodeLabel
    node_id: str
    properties: dict = field(default_factory=dict)
    # field_name -> (source, observed_at) - who last won the right to set this field.
    provenance: dict = field(default_factory=dict)
    last_observed_at: datetime | None = None


@dataclass
class EdgeState:
    rel_type: RelType
    from_id: str
    to_id: str
    source: str
    last_confirmed_at: datetime
    active: bool = True
    properties: dict = field(default_factory=dict)


class ReconciliationEngine:
    def __init__(self) -> None:
        self.nodes: dict[tuple[str, str], NodeState] = {}
        self.edges: dict[tuple[str, str, str], EdgeState] = {}
        self.change_log: list[ChangeEvent] = []
        self._id_to_label: dict[str, str] = {}

    # ---- writes ---------------------------------------------------------

    def apply_node_observation(self, obs: NodeObservation) -> list[ChangeEvent]:
        key = (obs.label.value, obs.node_id)
        events: list[ChangeEvent] = []
        is_new = key not in self.nodes
        node = self.nodes.setdefault(key, NodeState(label=obs.label, node_id=obs.node_id))
        self._id_to_label[obs.node_id] = obs.label.value

        changed_fields: list[str] = []
        for field_name, value in obs.properties.items():
            current_value = node.properties.get(field_name)
            current_prov = node.provenance.get(field_name)
            rule = field_owner_rule(field_name)

            if current_prov is None:
                should_update = True
            elif rule == "cmdb_wins":
                # cmdb always wins once it has an opinion; other sources may
                # only fill in a field cmdb (and nobody else) has set yet.
                should_update = obs.source == "cmdb" or current_prov[0] != "cmdb"
            else:  # most_recent_wins
                should_update = obs.observed_at >= current_prov[1]

            if should_update and current_value != value:
                node.properties[field_name] = value
                node.provenance[field_name] = (obs.source, obs.observed_at)
                changed_fields.append(field_name)

        node.last_observed_at = max(filter(None, [node.last_observed_at, obs.observed_at]))

        # Emit a change event both when a node first appears AND whenever an
        # existing node's fields actually change (e.g. a telemetry ping
        # flips a host's status) - the first version of this method only
        # fired on creation, which meant the live websocket feed never told
        # the dashboard about anything happening to a host it already knew
        # about. Re-confirming the exact same values every tick is NOT a
        # change and deliberately produces no event, so a healthy, stable
        # fleet doesn't spam the feed.
        if is_new:
            validate_node_properties(obs.label, node.properties)
        if is_new or changed_fields:
            events.append(
                ChangeEvent(
                    kind="node_upserted",
                    timestamp=obs.observed_at,
                    detail={"label": obs.label.value, "node_id": obs.node_id, "properties": dict(node.properties)},
                )
            )
        self.change_log.extend(events)
        return events

    def apply_edge_observation(self, obs: EdgeObservation) -> list[ChangeEvent]:
        key = (obs.rel_type.value, obs.from_id, obs.to_id)
        events: list[ChangeEvent] = []
        existing = self.edges.get(key)

        if obs.present:
            if existing is None or not existing.active:
                events.append(
                    ChangeEvent(
                        kind="edge_upserted",
                        timestamp=obs.observed_at,
                        detail={"rel_type": obs.rel_type.value, "from_id": obs.from_id, "to_id": obs.to_id},
                    )
                )
            self.edges[key] = EdgeState(
                rel_type=obs.rel_type,
                from_id=obs.from_id,
                to_id=obs.to_id,
                source=obs.source,
                last_confirmed_at=obs.observed_at,
                active=True,
                properties=obs.properties,
            )
        else:
            if existing is not None and existing.active:
                existing.active = False
                events.append(
                    ChangeEvent(
                        kind="edge_removed",
                        timestamp=obs.observed_at,
                        detail={"rel_type": obs.rel_type.value, "from_id": obs.from_id, "to_id": obs.to_id},
                    )
                )

        self.change_log.extend(events)
        return events

    # ---- reads ------------------------------------------------------------

    def stale_host_ids(self, now: datetime, ttl_seconds: float) -> list[str]:
        """Hosts no source has confirmed within the TTL window - the graph's view of them may no longer be true."""
        stale = []
        for (label, node_id), node in self.nodes.items():
            if label != NodeLabel.HOST.value or node.last_observed_at is None:
                continue
            if (now - node.last_observed_at).total_seconds() > ttl_seconds:
                stale.append(node_id)
        return stale

    def impact(self, start_label: NodeLabel, start_id: str) -> list[dict]:
        """
        Blast radius: everything that would be affected if `start_id` went
        down, by walking RUNS_ON/DEPENDS_ON edges backwards (if A RUNS_ON B
        or A DEPENDS_ON B, then A is affected when B is affected).

        Returns a list of {label, node_id, hops} ordered by distance, not
        including the starting node itself.
        """
        return self._traverse_requires(start_id, reverse=True)

    def dependencies(self, start_label: NodeLabel, start_id: str) -> list[dict]:
        """
        The opposite direction of impact(): everything `start_id` itself
        needs to be healthy, by walking RUNS_ON/DEPENDS_ON edges forwards.
        Same shape as impact() - a list of {label, node_id, hops}.
        """
        return self._traverse_requires(start_id, reverse=False)

    def _traverse_requires(self, start_id: str, *, reverse: bool) -> list[dict]:
        adjacency: dict[str, list[tuple[str, str]]] = defaultdict(list)
        for (rel_type, from_id, to_id), edge in self.edges.items():
            if not edge.active or rel_type not in REQUIRES_REL_TYPES:
                continue
            near, far = (to_id, from_id) if reverse else (from_id, to_id)
            label_of_far = self.label_of(far)
            if label_of_far is None:
                continue
            adjacency[near].append((label_of_far, far))

        visited = {start_id}
        queue: deque[tuple[str, int]] = deque([(start_id, 0)])
        result: list[dict] = []

        while queue:
            current_id, hops = queue.popleft()
            for label, neighbor_id in adjacency.get(current_id, []):
                if neighbor_id in visited:
                    continue
                visited.add(neighbor_id)
                result.append({"label": label, "node_id": neighbor_id, "hops": hops + 1})
                queue.append((neighbor_id, hops + 1))

        return result

    def label_of(self, node_id: str) -> str | None:
        return self._id_to_label.get(node_id)

    def all_nodes(self) -> list[NodeState]:
        return list(self.nodes.values())

    def all_active_edges(self) -> list[EdgeState]:
        return [e for e in self.edges.values() if e.active]
