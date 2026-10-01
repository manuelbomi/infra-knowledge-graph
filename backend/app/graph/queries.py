"""
Reference Cypher queries that do the same thing as the Python logic in
app/reconciliation/engine.py. These aren't called by the API (the API reads
from the fast in-memory engine - see neo4j_sync.py for why), but they're
real, correct queries you can paste into Neo4j Browser against the synced
graph to see the same answer the dashboard shows.
"""

# Blast radius: everything that would be affected if the given host went
# down. Walks RUNS_ON/DEPENDS_ON edges backwards, any number of hops.
BLAST_RADIUS = """
MATCH (start:Host {id: $host_id})
MATCH path = (dependent)-[:RUNS_ON|DEPENDS_ON*1..6]->(start)
RETURN DISTINCT dependent.id AS node_id, labels(dependent)[0] AS label, length(path) AS hops
ORDER BY hops
"""

# Hosts nothing has confirmed recently - the Cypher equivalent of
# ReconciliationEngine.stale_host_ids(), if `last_seen` has been synced onto
# the Host node as an ISO timestamp string.
STALE_HOSTS = """
MATCH (h:Host)
WHERE h.last_seen IS NOT NULL AND datetime(h.last_seen) < datetime() - duration({seconds: $ttl_seconds})
RETURN h.id AS node_id, h.last_seen AS last_seen
"""
