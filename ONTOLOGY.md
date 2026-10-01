# Ontology reference

This is the fixed vocabulary every data source has to translate its information
into before it goes in the graph. If you're adding a new ingestion source, this
is the contract it has to satisfy. The code version of this lives in
`backend/app/ontology/schema.py` and is enforced on every write.

## Node types

| Label | What it represents | Required properties |
|---|---|---|
| `Region` | A geographic region (e.g. "US East") | `id`, `name` |
| `DataCenter` | A physical/logical data center inside a region | `id`, `name`, `region_id` |
| `Host` | A single machine | `id`, `hostname` |
| `Service` | A deployable piece of software | `id`, `name` |
| `IncidentEvent` | A point-in-time record that something went unhealthy | `id`, `started_at` |

Dependency between two services is modeled as a **relationship**
(`DEPENDS_ON`), not a node. A dependency isn't a "thing" with its own identity
-- it's a fact about the relationship between two services, and it needs to
carry per-edge metadata (confidence, which source reported it) that only makes
sense attached to an edge.

## Relationship types

| Type | Direction | Meaning |
|---|---|---|
| `CONTAINS` | Region → DataCenter → Host | Physical/logical containment |
| `RUNS_ON` | Service → Host | This service instance requires this host to be up |
| `DEPENDS_ON` | Service → Service | This service requires that service to be up |
| `CONNECTS_TO` | Host → Host | A network link exists between two hosts |
| `AFFECTS` | IncidentEvent → Host \| Service | This incident affected this entity |

`RUNS_ON` and `DEPENDS_ON` are the two relationship types that represent a real
health dependency ("if the thing on the other end of this edge goes down, I'm
affected too"). The blast-radius query in `GET /api/impact/{id}` only follows
these two edge types. `CONTAINS` and `CONNECTS_TO` describe structure, not
health dependency, so they're deliberately excluded from that traversal --
otherwise "what breaks if this region goes down" would include every host in
every data center in that region, whether or not anything actually depends on
it being up.

## Edge properties worth knowing about

`RUNS_ON` edges carry:
- `declared` (bool) -- did the CMDB say this placement should exist?
- `state` -- `active` (discovery confirmed it recently) or `stale` (it hasn't
  been reconfirmed within the staleness window)
- `last_seen` -- timestamp discovery last confirmed it

`DEPENDS_ON` edges carry:
- `declared` / `observed` (bool each) -- did the CMDB declare it, did
  discovery observe it, or both?
- `confidence` (0.0-1.0) -- see `app/ingest/rules.py::dependency_confidence`
  for exactly how this is computed
- `source_label` -- a human-readable reason for the confidence score

See the README's "How the reconciliation actually works" section for the
reasoning behind these fields.
