"""
Read queries against the graph. Kept separate from the reconciler (which
writes) and from main.py (which just wires HTTP routes to these functions).
"""

from app.db import run_query
from app.ontology.schema import REQUIRES_REL_TYPES


async def get_full_graph() -> dict:
    """Everything needed to render the initial graph view: all nodes, all edges."""
    node_rows = await run_query(
        "MATCH (n) RETURN labels(n)[0] AS label, properties(n) AS props"
    )
    edge_rows = await run_query(
        """
        MATCH (a)-[r]->(b)
        RETURN a.id AS source, b.id AS target, type(r) AS rel_type, properties(r) AS props
        """
    )

    nodes = [{"id": row["props"]["id"], "label": row["label"], **row["props"]} for row in node_rows]
    edges = [
        {"source": row["source"], "target": row["target"], "rel_type": row["rel_type"], **row["props"]}
        for row in edge_rows
    ]
    return {"nodes": nodes, "edges": edges}


async def get_node_detail(node_id: str) -> dict | None:
    node_rows = await run_query(
        "MATCH (n {id: $id}) RETURN labels(n)[0] AS label, properties(n) AS props",
        {"id": node_id},
    )
    if not node_rows:
        return None

    outgoing = await run_query(
        """
        MATCH (n {id: $id})-[r]->(m)
        RETURN type(r) AS rel_type, m.id AS target_id, labels(m)[0] AS target_label, properties(r) AS props
        """,
        {"id": node_id},
    )
    incoming = await run_query(
        """
        MATCH (n {id: $id})<-[r]-(m)
        RETURN type(r) AS rel_type, m.id AS source_id, labels(m)[0] AS source_label, properties(r) AS props
        """,
        {"id": node_id},
    )

    row = node_rows[0]
    return {
        "id": node_id,
        "label": row["label"],
        "properties": row["props"],
        "outgoing_relationships": outgoing,
        "incoming_relationships": incoming,
    }


async def get_impact(node_id: str) -> dict:
    """Blast-radius query.

    Downstream = everything that would be affected if `node_id` goes down,
    found by following DEPENDS_ON / RUNS_ON edges *backwards* (i.e. finding
    everyone whose edge points at this node).

    Upstream = everything `node_id` itself requires to be healthy, found by
    following those same edge types *forwards* from this node.

    Depth is capped at 6 hops -- plenty for this topology, and a sane
    circuit breaker against runaway traversals on a much bigger graph.
    """
    rel_pattern = "|".join(REQUIRES_REL_TYPES)

    downstream = await run_query(
        f"""
        MATCH (impacted)-[:{rel_pattern}*1..6]->(target {{id: $id}})
        RETURN DISTINCT impacted.id AS id, labels(impacted)[0] AS label
        """,
        {"id": node_id},
    )
    upstream = await run_query(
        f"""
        MATCH (target {{id: $id}})-[:{rel_pattern}*1..6]->(dependency)
        RETURN DISTINCT dependency.id AS id, labels(dependency)[0] AS label
        """,
        {"id": node_id},
    )

    return {
        "node_id": node_id,
        "downstream_impact": downstream,
        "upstream_dependencies": upstream,
    }


async def neo4j_is_reachable() -> bool:
    try:
        await run_query("RETURN 1")
        return True
    except Exception:
        return False
