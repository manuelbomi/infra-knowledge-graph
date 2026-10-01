"""
The ontology: the fixed vocabulary of node types and relationship types that
every ingestion source has to translate its data into.

Why this file exists: three different source systems (a CMDB, a service-mesh
discovery feed, and a telemetry feed) each describe infrastructure using
their own shapes and field names. If we let each one write whatever it wants
into the graph, we'd end up with three incompatible mini-graphs instead of
one coherent picture. This file is the contract -- every adapter in
app/ingest/ has to produce data that fits these node and relationship types.

See ONTOLOGY.md at the repo root for the human-readable version of this.
"""

from enum import Enum


class NodeLabel(str, Enum):
    REGION = "Region"
    DATA_CENTER = "DataCenter"
    HOST = "Host"
    SERVICE = "Service"
    INCIDENT_EVENT = "IncidentEvent"


class RelType(str, Enum):
    CONTAINS = "CONTAINS"          # Region -> DataCenter -> Host (physical/logical containment)
    RUNS_ON = "RUNS_ON"            # Service -> Host (a service instance requires this host)
    DEPENDS_ON = "DEPENDS_ON"      # Service -> Service (a service requires another service)
    CONNECTS_TO = "CONNECTS_TO"    # Host -> Host (a network link exists between two hosts)
    AFFECTS = "AFFECTS"            # IncidentEvent -> Host | Service


# Relationship types that represent "A requires B to be healthy". We treat
# RUNS_ON and DEPENDS_ON as the same kind of edge for impact analysis: if B
# goes down, anything that reaches B through one of these edges is at risk.
# CONTAINS and CONNECTS_TO are topology/structure, not a health dependency,
# so they're deliberately left out of blast-radius traversals.
REQUIRES_REL_TYPES = (RelType.DEPENDS_ON.value, RelType.RUNS_ON.value)


# Required properties per node label. Kept intentionally small -- this is
# enforced in ingest/reconciler.py before anything is written to Neo4j, and
# mirrored as uniqueness constraints in ensure_constraints() below.
REQUIRED_PROPERTIES = {
    NodeLabel.REGION: {"id", "name"},
    NodeLabel.DATA_CENTER: {"id", "name", "region_id"},
    NodeLabel.HOST: {"id", "hostname"},
    NodeLabel.SERVICE: {"id", "name"},
    NodeLabel.INCIDENT_EVENT: {"id", "started_at"},
}


def validate_node_properties(label: NodeLabel, properties: dict) -> None:
    """Raise if a node is missing a property the ontology says it must have.

    This runs before every write. Catching a malformed record here, with a
    clear error, is a lot cheaper than debugging a graph that silently has
    nodes missing fields the frontend assumes exist.
    """
    missing = REQUIRED_PROPERTIES[label] - properties.keys()
    if missing:
        raise ValueError(f"{label.value} node is missing required properties: {missing}")


def constraint_statements() -> list[str]:
    """Cypher statements that make 'id' unique per node label.

    Running these at startup is what makes every MERGE in the ingest
    adapters idempotent -- re-ingesting the same CMDB snapshot twice updates
    the existing node instead of creating a duplicate.
    """
    statements = []
    for label in NodeLabel:
        statements.append(
            f"CREATE CONSTRAINT IF NOT EXISTS FOR (n:{label.value}) REQUIRE n.id IS UNIQUE"
        )
    return statements
