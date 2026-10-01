"""
The CMDB adapter: slow-changing, authoritative for structure and ownership.

Real CMDBs are usually updated by hand or by a nightly sync job, not in real
time - that's exactly why they're trusted for "which region is this host
in" and "who owns it" (see trust.py) but not for "is it healthy right now".
This adapter reflects that by only producing a full snapshot, never a
partial update, and by never touching live-state fields like `status`.
"""

from __future__ import annotations

from datetime import datetime

from app.ontology.schema import NodeLabel
from app.reconciliation.models import NodeObservation

from .topology import PLAN

SOURCE_NAME = "cmdb"


def snapshot(now: datetime) -> list[NodeObservation]:
    observations: list[NodeObservation] = []

    for region in PLAN.regions:
        observations.append(
            NodeObservation(NodeLabel.REGION, region["id"], {"id": region["id"], "name": region["name"]}, SOURCE_NAME, now)
        )

    for dc in PLAN.datacenters:
        observations.append(
            NodeObservation(
                NodeLabel.DATA_CENTER,
                dc["id"],
                {"id": dc["id"], "name": dc["name"], "region_id": dc["region_id"]},
                SOURCE_NAME,
                now,
            )
        )

    for host in PLAN.hosts:
        observations.append(
            NodeObservation(
                NodeLabel.HOST,
                host.id,
                {
                    "id": host.id,
                    "hostname": host.hostname,
                    "region_id": host.region_id,
                    "datacenter_id": host.datacenter_id,
                    "owner": host.owner,
                },
                SOURCE_NAME,
                now,
            )
        )

    return observations
