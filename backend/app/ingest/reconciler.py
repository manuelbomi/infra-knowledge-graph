"""
The reconciliation layer: takes output from the three ingestion sources and
merges it into one Neo4j graph that matches the ontology in
app/ontology/schema.py.

This is the hard part of the whole project. Any one source, on its own, is
easy to load into a graph. The actual problem is that the three sources
update at different speeds and sometimes flatly disagree:

  * CMDB: changes rarely, tells you what *should* exist.
  * Discovery: changes every few seconds, tells you what's *actually*
    running and talking to what, but can miss things for a cycle.
  * Telemetry: changes every few seconds, tells you what's healthy.

Two load-bearing decisions live here (both backed by pure, unit-tested
functions in rules.py):

  1. Staleness -- a declared fact that discovery hasn't reconfirmed recently
     gets marked stale instead of being trusted forever.
  2. Conflicting dependency edges -- when the CMDB and discovery disagree
     about whether service A depends on service B, we keep BOTH opinions on
     the edge (declared / observed / both) with a confidence score, instead
     of silently picking one and throwing the other away.
"""

from datetime import datetime, timezone

from app.db import run_query
from app.ingest import rules
from app.ingest.cmdb_source import get_cmdb_snapshot
from app.ingest.discovery_source import poll_discovery
from app.ingest.telemetry_source import poll_telemetry
from app.ontology.schema import NodeLabel, RelType, constraint_statements, validate_node_properties

# Reconciliation watermarks kept in process memory. In a production system
# these would be read back from the graph (or a dedicated state store)
# instead of living in a module-level dict, so reconciliation survives a
# restart -- called out again in the README's "what's simplified" section.
_runs_on_last_seen: dict[tuple[str, str], str | None] = {}
_depends_on_last_confirmed: dict[tuple[str, str], str | None] = {}
_previous_health: dict[str, str] = {}


async def ensure_schema() -> None:
    for statement in constraint_statements():
        await run_query(statement)


async def load_cmdb_snapshot() -> None:
    """One-time load of the static topology. Safe to re-run (MERGE is idempotent)."""
    snapshot = get_cmdb_snapshot()

    for region in snapshot["regions"]:
        validate_node_properties(NodeLabel.REGION, region)
        await run_query(
            "MERGE (r:Region {id: $id}) SET r.name = $name", region
        )

    for dc in snapshot["data_centers"]:
        validate_node_properties(NodeLabel.DATA_CENTER, dc)
        await run_query(
            """
            MERGE (d:DataCenter {id: $id})
            SET d.name = $name, d.region_id = $region_id
            WITH d
            MATCH (r:Region {id: $region_id})
            MERGE (r)-[:CONTAINS]->(d)
            """,
            dc,
        )

    for host in snapshot["hosts"]:
        validate_node_properties(NodeLabel.HOST, host)
        await run_query(
            """
            MERGE (h:Host {id: $id})
            SET h.hostname = $hostname, h.ip_address = $ip_address,
                h.data_center_id = $data_center_id
            WITH h
            MATCH (d:DataCenter {id: $data_center_id})
            MERGE (d)-[:CONTAINS]->(h)
            """,
            host,
        )

    for service in snapshot["services"]:
        validate_node_properties(NodeLabel.SERVICE, service)
        await run_query("MERGE (s:Service {id: $id}) SET s.name = $name", service)

    for service_id, host_id in snapshot["declared_runs_on"]:
        await run_query(
            """
            MATCH (s:Service {id: $service_id}), (h:Host {id: $host_id})
            MERGE (s)-[r:RUNS_ON]->(h)
            ON CREATE SET r.declared = true, r.state = 'stale', r.last_seen = null
            """,
            {"service_id": service_id, "host_id": host_id},
        )

    for service_id, depends_on_id in snapshot["declared_depends_on"]:
        label, confidence = rules.dependency_confidence(declared=True, observed=False)
        await run_query(
            """
            MATCH (a:Service {id: $service_id}), (b:Service {id: $depends_on_id})
            MERGE (a)-[r:DEPENDS_ON]->(b)
            ON CREATE SET r.declared = true, r.observed = false,
                          r.confidence = $confidence, r.source_label = $label
            """,
            {
                "service_id": service_id,
                "depends_on_id": depends_on_id,
                "confidence": confidence,
                "label": label,
            },
        )


async def reconcile_cycle() -> dict:
    """Run one pass of discovery + telemetry polling and merge it into the graph.

    Returns a delta summary (not the whole graph) so callers can push a
    small, incremental update over the websocket instead of re-sending
    everything on every tick.
    """
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()

    cmdb = get_cmdb_snapshot()
    discovery = poll_discovery()
    telemetry = poll_telemetry()

    updated_nodes: list[dict] = []
    updated_edges: list[dict] = []
    new_incidents: list[dict] = []

    # --- RUNS_ON: did discovery reconfirm each declared placement? ---
    observed_now_set = set(discovery["observed_runs_on"])
    for service_id, host_id in cmdb["declared_runs_on"]:
        key = (service_id, host_id)
        observed_now = key in observed_now_set
        if observed_now:
            _runs_on_last_seen[key] = now_iso
            state = "active"
        else:
            state = "stale" if rules.is_stale(_runs_on_last_seen.get(key), now, ttl_seconds=30) else "active"

        await run_query(
            """
            MATCH (s:Service {id: $service_id})-[r:RUNS_ON]->(h:Host {id: $host_id})
            SET r.state = $state, r.last_seen = $last_seen
            """,
            {"service_id": service_id, "host_id": host_id, "state": state,
             "last_seen": _runs_on_last_seen.get(key)},
        )
        updated_edges.append(
            {"from": service_id, "to": host_id, "rel_type": RelType.RUNS_ON.value, "state": state}
        )

    # --- DEPENDS_ON: reconcile declared vs. observed dependency claims ---
    declared_set = set(cmdb["declared_depends_on"])
    observed_set = set(discovery["observed_depends_on"])
    for pair in declared_set | observed_set:
        declared = pair in declared_set
        observed = pair in observed_set
        label, confidence = rules.dependency_confidence(declared, observed)
        if observed:
            _depends_on_last_confirmed[pair] = now_iso

        await run_query(
            """
            MATCH (a:Service {id: $a}), (b:Service {id: $b})
            MERGE (a)-[r:DEPENDS_ON]->(b)
            SET r.declared = $declared, r.observed = $observed,
                r.confidence = $confidence, r.source_label = $label,
                r.last_confirmed = $last_confirmed
            """,
            {
                "a": pair[0], "b": pair[1], "declared": declared, "observed": observed,
                "confidence": confidence, "label": label,
                "last_confirmed": _depends_on_last_confirmed.get(pair),
            },
        )
        updated_edges.append(
            {
                "from": pair[0], "to": pair[1], "rel_type": RelType.DEPENDS_ON.value,
                "confidence": confidence, "source_label": label,
            }
        )

    # --- Telemetry: host + service health, and incident creation on transitions ---
    for host_id, reading in telemetry["host_status"].items():
        health = rules.classify_health(reading["status"], stale=False)
        await _apply_health_update(NodeLabel.HOST, host_id, reading, health, now_iso)
        updated_nodes.append({"id": host_id, "label": NodeLabel.HOST.value, "health": health,
                               "latency_ms": reading["latency_ms"]})
        incident = await _maybe_raise_incident(host_id, health, now_iso)
        if incident:
            new_incidents.append(incident)

    for service_id, reading in telemetry["service_status"].items():
        health = rules.classify_health(reading["status"], stale=False)
        await _apply_health_update(NodeLabel.SERVICE, service_id, reading, health, now_iso)
        updated_nodes.append({"id": service_id, "label": NodeLabel.SERVICE.value, "health": health,
                               "latency_ms": reading["latency_ms"]})
        incident = await _maybe_raise_incident(service_id, health, now_iso)
        if incident:
            new_incidents.append(incident)

    return {
        "timestamp": now_iso,
        "updated_nodes": updated_nodes,
        "updated_edges": updated_edges,
        "new_incidents": new_incidents,
    }


async def _apply_health_update(label: NodeLabel, entity_id: str, reading: dict, health: str, now_iso: str) -> None:
    await run_query(
        f"""
        MATCH (n:{label.value} {{id: $id}})
        SET n.status = $status, n.latency_ms = $latency_ms,
            n.health = $health, n.last_heartbeat = $last_heartbeat
        """,
        {"id": entity_id, "status": reading["status"], "latency_ms": reading["latency_ms"],
         "health": health, "last_heartbeat": now_iso},
    )


async def _maybe_raise_incident(entity_id: str, health: str, now_iso: str) -> dict | None:
    """Create an IncidentEvent node the moment something flips to unhealthy.

    Only fires on the up->down transition (not every cycle it stays down),
    the same way a real alerting system pages once for an outage rather than
    once per health check.
    """
    was_healthy = _previous_health.get(entity_id, "healthy") == "healthy"
    _previous_health[entity_id] = health

    if was_healthy and health == "unhealthy":
        incident_id = f"incident-{entity_id}-{now_iso}"
        await run_query(
            """
            MERGE (i:IncidentEvent {id: $incident_id})
            SET i.started_at = $started_at, i.affected_entity_id = $entity_id
            WITH i
            MATCH (n {id: $entity_id})
            MERGE (i)-[:AFFECTS]->(n)
            """,
            {"incident_id": incident_id, "started_at": now_iso, "entity_id": entity_id},
        )
        return {"id": incident_id, "affects": entity_id, "started_at": now_iso}
    return None
