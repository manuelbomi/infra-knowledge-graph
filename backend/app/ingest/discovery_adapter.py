"""
The service-mesh discovery adapter: re-discovers the live service topology
on every tick and reports it as a full snapshot. Because it's a snapshot,
this adapter is responsible for noticing when something it used to see is
gone and explicitly reporting that (an EdgeObservation with present=False)
rather than just quietly stopping to mention it - a real service mesh
control plane behaves the same way: it knows the current state, not a diff.

On top of the stable topology plan, this adapter occasionally reassigns a
service to a different host (simulating a redeploy) and occasionally drops
or restores a dependency edge (simulating a service picking up or dropping
a call to another service) - small, infrequent changes, so the live
dashboard has something real to show without the topology looking chaotic.
"""

from __future__ import annotations

import random
from datetime import datetime

from app.ontology.schema import NodeLabel, RelType
from app.reconciliation.models import EdgeObservation, NodeObservation

from .topology import PLAN

SOURCE_NAME = "service_mesh_discovery"


class DiscoveryAdapter:
    def __init__(self, seed: int = 4242) -> None:
        self._rnd = random.Random(seed)
        # Mutable "current belief" state, starting from the plan. Adapters
        # mutate their own copy, never the shared plan.
        self._current_hosts: dict[str, list[str]] = {k: list(v) for k, v in PLAN.service_hosts.items()}
        self._current_depends_on: dict[str, set[str]] = {s.id: set(s.depends_on) for s in PLAN.services}

    def tick(self, now: datetime) -> tuple[list[NodeObservation], list[EdgeObservation]]:
        node_obs: list[NodeObservation] = []
        edge_obs: list[EdgeObservation] = []

        for service in PLAN.services:
            node_obs.append(
                NodeObservation(NodeLabel.SERVICE, service.id, {"id": service.id, "name": service.name}, SOURCE_NAME, now)
            )

        self._maybe_redeploy_a_service()
        self._maybe_toggle_a_dependency_edge()

        for service in PLAN.services:
            for host_id in self._current_hosts[service.id]:
                edge_obs.append(EdgeObservation(RelType.RUNS_ON, service.id, host_id, SOURCE_NAME, now, present=True))
            # Report removal for any host this service used to run on but no longer does.
            for host_id in PLAN.service_hosts[service.id]:
                if host_id not in self._current_hosts[service.id]:
                    edge_obs.append(EdgeObservation(RelType.RUNS_ON, service.id, host_id, SOURCE_NAME, now, present=False))

            all_possible_targets = {s.id for s in PLAN.services} - {service.id}
            for target in all_possible_targets:
                present = target in self._current_depends_on[service.id]
                edge_obs.append(EdgeObservation(RelType.DEPENDS_ON, service.id, target, SOURCE_NAME, now, present=present))

        return node_obs, edge_obs

    def _maybe_redeploy_a_service(self) -> None:
        if self._rnd.random() > 0.05:
            return
        service = self._rnd.choice(PLAN.services)
        new_host = self._rnd.choice(PLAN.hosts).id
        self._current_hosts[service.id] = [new_host]

    def _maybe_toggle_a_dependency_edge(self) -> None:
        if self._rnd.random() > 0.08:
            return
        service = self._rnd.choice(PLAN.services)
        candidates = [s.id for s in PLAN.services if s.id != service.id]
        target = self._rnd.choice(candidates)
        current = self._current_depends_on[service.id]
        if target in current:
            current.discard(target)
        else:
            current.add(target)
