"""
Mirrors the reconciliation engine's in-memory state into Neo4j.

Why bother, if the API already serves from memory? Two reasons:

1. Durability and real Cypher access. The in-memory engine is fast but it's
   gone the moment the process restarts, and nobody can run an ad-hoc query
   against a Python dict. Neo4j gives you both - open Neo4j Browser (see
   README) and run the same blast-radius logic as a real Cypher query
   against the live topology.
2. It's the natural seam for scaling out later. The moment this needs to
   run as more than one process, the in-memory engine stops being a single
   source of truth and Neo4j has to become the real one - this sync job is
   what already keeps it current, so that cutover is a routing change, not
   a rewrite.

Every write here is a MERGE, which makes it safe to replay the same
observation twice - re-running sync after a crash just re-asserts the
current state rather than duplicating anything. If Neo4j isn't reachable
(for example, nobody ran `docker-compose up`), sync_graph() logs a warning
and returns instead of crashing the whole app - the dashboard and API keep
working off the in-memory engine either way.
"""

from __future__ import annotations

import logging

from neo4j.exceptions import ServiceUnavailable

from app.db import run_query
from app.ontology.schema import constraint_statements
from app.reconciliation.engine import ReconciliationEngine

logger = logging.getLogger(__name__)

_constraints_ensured = False


async def ensure_constraints() -> bool:
    global _constraints_ensured
    if _constraints_ensured:
        return True
    try:
        for statement in constraint_statements():
            await run_query(statement)
        _constraints_ensured = True
        return True
    except ServiceUnavailable:
        logger.warning("Neo4j is not reachable - skipping constraint setup, running on in-memory state only.")
        return False


async def sync_graph(engine: ReconciliationEngine) -> bool:
    """Pushes the engine's current nodes and active edges into Neo4j as idempotent MERGEs."""
    if not await ensure_constraints():
        return False

    try:
        for node in engine.all_nodes():
            await run_query(
                f"MERGE (n:{node.label.value} {{id: $id}}) SET n += $properties",
                {"id": node.node_id, "properties": node.properties},
            )
        for edge in engine.all_active_edges():
            await run_query(
                f"""
                MATCH (a {{id: $from_id}}), (b {{id: $to_id}})
                MERGE (a)-[r:{edge.rel_type.value}]->(b)
                SET r.source = $source, r.last_confirmed_at = $last_confirmed_at
                """,
                {
                    "from_id": edge.from_id,
                    "to_id": edge.to_id,
                    "source": edge.source,
                    "last_confirmed_at": edge.last_confirmed_at.isoformat(),
                },
            )
        return True
    except ServiceUnavailable:
        logger.warning("Neo4j became unreachable mid-sync - in-memory state is unaffected, will retry next tick.")
        return False
