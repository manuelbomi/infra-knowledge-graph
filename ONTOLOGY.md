# The ontology

This is the fixed vocabulary every source has to translate its data into before it goes in the graph. It's enforced in code at `backend/app/ontology/schema.py` - this file is the plain-English version of the same thing.

Why have one at all? Because the three source systems (a CMDB, a service-mesh discovery feed, and a telemetry feed) each describe infrastructure in their own shape, with their own field names. Without a shared vocabulary, you don't get one graph - you get three incompatible mini-graphs sitting next to each other that happen to be drawn with the same tool. The ontology is what makes "the same real host, described three different ways" actually resolve into one node.

## Node types

| Node | What it represents | Required properties |
|---|---|---|
| `Region` | A geographic/cloud region (e.g. us-east-1) | `id`, `name` |
| `DataCenter` | A data center inside a region | `id`, `name`, `region_id` |
| `Host` | A physical or virtual machine | `id`, `hostname` |
| `Service` | A deployable application/service | `id`, `name` |
| `IncidentEvent` | Something that went wrong, tied to a host or service | `id`, `started_at` |

A node is rejected before it's ever written if it's missing a required property - that validation happens in `validate_node_properties()`, and it runs on every single observation, not just on initial creation.

## Relationship types

| Relationship | Direction | Meaning |
|---|---|---|
| `CONTAINS` | Region -> DataCenter -> Host | Physical/logical containment |
| `RUNS_ON` | Service -> Host | This service has an instance running on this host |
| `DEPENDS_ON` | Service -> Service | This service needs the other one to do its job |
| `CONNECTS_TO` | Host -> Host | A network link exists between two hosts |
| `AFFECTS` | IncidentEvent -> Host or Service | This incident is affecting this node |

### Why `RUNS_ON` and `DEPENDS_ON` are special

Blast-radius analysis ("what breaks if this host goes down?") only makes sense over edges that represent an actual operational dependency. `RUNS_ON` and `DEPENDS_ON` both mean "the source node needs the target node to be healthy" - so impact analysis walks exactly those two edge types, backwards, from the failing node. `CONTAINS` and `CONNECTS_TO` describe structure and network topology, not health dependency, so they're deliberately left out of that traversal - a host being in the same data center as another host doesn't mean one failing breaks the other.

## Who owns which field, when sources disagree

Every property has one rule that decides which source wins if two of them report different values for it (see `backend/app/reconciliation/trust.py`):

- **`region_id`, `datacenter_id`, `owner`, `name`** - the CMDB always wins, once it has an opinion. These are facts a human maintains by hand, and the CMDB is the system of record for that. A discovery or telemetry feed is allowed to fill the field in if the CMDB hasn't reported it yet, but the moment the CMDB does report, it takes over.
- **Everything else (`status`, `last_seen`, and anything not explicitly listed above)** - most recent observation wins. These are live-state fields where "what's true right now" matters more than which source said it.

## Staleness

A host is considered **stale** if no source has confirmed anything about it within a configurable TTL (`staleness_ttl_seconds` in `backend/app/config.py`, default 30 seconds for this demo - a real deployment would set this to minutes, matched to how often its actual telemetry agents check in). Staleness isn't the same as "unhealthy" - a stale host might be perfectly fine, it just means the graph's view of it might be out of date, and the dashboard flags that honestly instead of pretending the last known state is still current.
