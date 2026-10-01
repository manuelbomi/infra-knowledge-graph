"""
The "ground truth" shape of the fake infrastructure all three adapters pull
from. Having one shared plan, instead of each adapter inventing its own
hosts and services, is what lets the three sources genuinely describe the
*same* fleet while still disagreeing about details - which is the whole
point of this project. Each adapter reads from here but reports it through
its own source-specific lens (see cmdb_adapter.py, discovery_adapter.py,
telemetry_adapter.py for how each one distorts or narrows this view).

Reproducible via a fixed seed - the topology's shape is stable across
restarts, but the three adapters still introduce live, time-based change on
top of it (host status flips, services getting redeployed to a different
host, a dependency edge disappearing), which is what makes the dashboard
visibly "live" instead of a static diagram.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

SEED = 71

REGIONS = [
    {"id": "region-use1", "name": "us-east-1"},
    {"id": "region-usw2", "name": "us-west-2"},
    {"id": "region-euw1", "name": "eu-west-1"},
]

OWNERS = ["platform-team", "checkout-team", "search-team", "data-team"]


@dataclass
class HostPlan:
    id: str
    hostname: str
    region_id: str
    datacenter_id: str
    owner: str


@dataclass
class ServicePlan:
    id: str
    name: str
    # Dependency edges are "this service depends on these other services".
    depends_on: list[str] = field(default_factory=list)


def _build_datacenters() -> list[dict]:
    datacenters = []
    for region in REGIONS:
        for suffix in ("a", "b"):
            datacenters.append(
                {"id": f"{region['id']}-dc-{suffix}", "name": f"{region['name']}-dc-{suffix}", "region_id": region["id"]}
            )
    return datacenters


def _build_hosts(datacenters: list[dict], rnd: random.Random) -> list[HostPlan]:
    hosts = []
    for i in range(36):
        dc = datacenters[i % len(datacenters)]
        hosts.append(
            HostPlan(
                id=f"host-{i:03d}",
                hostname=f"host-{i:03d}",
                region_id=dc["region_id"],
                datacenter_id=dc["id"],
                owner=rnd.choice(OWNERS),
            )
        )
    return hosts


def _build_services() -> list[ServicePlan]:
    # A small, realistic-looking dependency chain rather than a random
    # graph, so "blast radius" demos make intuitive sense: frontend depends
    # on the edge API, which depends on two backend services, both of which
    # depend on a shared database proxy.
    return [
        ServicePlan("svc-frontend", "web-frontend", depends_on=["svc-edge-api"]),
        ServicePlan("svc-edge-api", "edge-api", depends_on=["svc-checkout", "svc-catalog"]),
        ServicePlan("svc-checkout", "checkout", depends_on=["svc-db-proxy", "svc-payments"]),
        ServicePlan("svc-catalog", "catalog", depends_on=["svc-db-proxy", "svc-search"]),
        ServicePlan("svc-payments", "payments", depends_on=["svc-db-proxy"]),
        ServicePlan("svc-search", "search-index", depends_on=[]),
        ServicePlan("svc-db-proxy", "db-proxy", depends_on=[]),
        ServicePlan("svc-notifications", "notifications", depends_on=["svc-edge-api"]),
    ]


class TopologyPlan:
    def __init__(self) -> None:
        rnd = random.Random(SEED)
        self.regions = REGIONS
        self.datacenters = _build_datacenters()
        self.hosts = _build_hosts(self.datacenters, rnd)
        self.services = _build_services()
        # Each service normally runs on 1-2 hosts, assigned up front.
        self.service_hosts: dict[str, list[str]] = {}
        for i, svc in enumerate(self.services):
            host_count = 2 if i % 3 == 0 else 1
            assigned = rnd.sample(self.hosts, host_count)
            self.service_hosts[svc.id] = [h.id for h in assigned]


PLAN = TopologyPlan()
