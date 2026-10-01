"""
The telemetry adapter: frequent, lightweight heartbeat pings per host.

This is the source that drives `status` and `last_seen` (see trust.py -
both are "most recent wins" fields, which is exactly what a heartbeat feed
should win). It's also the one adapter that can fail to report at all for a
given host on a given tick, simulating a dropped heartbeat - that's what
lets the staleness mechanism in the reconciliation engine actually get
exercised instead of every host always looking perfectly fresh.

When a host flips to "unhealthy", this adapter also raises an IncidentEvent
node and an AFFECTS edge pointing at that host - a crude stand-in for a
real alerting pipeline, but enough to show the ontology's IncidentEvent
type actually being used for something, not just defined and ignored.
"""

from __future__ import annotations

import random
from datetime import datetime

from app.ontology.schema import NodeLabel, RelType
from app.reconciliation.models import EdgeObservation, NodeObservation

from .topology import PLAN

SOURCE_NAME = "telemetry"

STATUS_WEIGHTS = [("healthy", 0.92), ("degraded", 0.06), ("unhealthy", 0.02)]


class TelemetryAdapter:
    def __init__(self, seed: int = 909) -> None:
        self._rnd = random.Random(seed)
        self._incident_counter = 0

    def tick(self, now: datetime) -> tuple[list[NodeObservation], list[EdgeObservation]]:
        node_obs: list[NodeObservation] = []
        edge_obs: list[EdgeObservation] = []

        for host in PLAN.hosts:
            # ~10% chance this host's heartbeat simply doesn't arrive this
            # tick - over several ticks in a row, this is what makes the
            # staleness TTL in the reconciliation engine actually trigger.
            if self._rnd.random() < 0.10:
                continue

            status = self._weighted_status()
            node_obs.append(
                NodeObservation(
                    NodeLabel.HOST,
                    host.id,
                    {"id": host.id, "hostname": host.hostname, "status": status, "last_seen": now.isoformat()},
                    SOURCE_NAME,
                    now,
                )
            )

            if status == "unhealthy":
                self._incident_counter += 1
                incident_id = f"incident-{host.id}-{self._incident_counter}"
                node_obs.append(
                    NodeObservation(
                        NodeLabel.INCIDENT_EVENT,
                        incident_id,
                        {"id": incident_id, "started_at": now.isoformat(), "severity": "high", "summary": f"{host.hostname} reporting unhealthy"},
                        SOURCE_NAME,
                        now,
                    )
                )
                edge_obs.append(EdgeObservation(RelType.AFFECTS, incident_id, host.id, SOURCE_NAME, now))

        return node_obs, edge_obs

    def _weighted_status(self) -> str:
        roll = self._rnd.random()
        cumulative = 0.0
        for status, weight in STATUS_WEIGHTS:
            cumulative += weight
            if roll <= cumulative:
                return status
        return STATUS_WEIGHTS[-1][0]
