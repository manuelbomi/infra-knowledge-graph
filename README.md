# Infrastructure Knowledge Graph

A live, queryable graph of "what's running where" for a piece of infrastructure - regions, data centers, hosts, services, and how they all depend on each other - built on Neo4j, with a dashboard that updates in real time as the infrastructure changes.

## The problem this solves

If you've worked on any infrastructure or platform team, you've run into this: nobody has one single, trustworthy answer to "what's actually running right now, and what depends on what?"

Usually the truth is spread across several systems that don't agree with each other:

- Your **CMDB** (configuration management database) says what *should* exist - but it's often stale, because keeping it perfectly in sync with reality is nobody's full-time job.
- A **service discovery** feed (a service mesh, an agent, whatever) tells you what's *actually* talking to what right now - but it re-discovers the world from scratch on every scan, so it can disagree with what it said five minutes ago.
- A **telemetry/health-check** feed tells you what's healthy - but a heartbeat going quiet doesn't necessarily mean something is down, it might just mean you haven't heard from it recently.

None of these three sources is "the truth" on its own. The interesting engineering problem isn't storing a graph - Neo4j does that part for you. The interesting problem is **reconciling** three sources that update at different speeds and sometimes flatly disagree, into one graph you can actually trust enough to ask it questions like "if this host goes down, what breaks?"

That reconciliation logic is the core of this project.

## What "knowledge graph" and "operational ontology" actually mean here

Two terms that sound more intimidating than they are:

- **Knowledge graph** - just a graph database (nodes + relationships) where the nodes and relationships represent real things you care about (hosts, services, incidents) instead of generic rows in a table. The advantage over a normal database is that questions like "what depends on what, transitively, five hops away?" are a single query instead of a pile of joins.
- **Operational ontology** - the fixed vocabulary of node types and relationship types everything has to fit into. Before you can reconcile three different sources, they all have to agree on what a "Host" is and what "DEPENDS_ON" means. See [`ONTOLOGY.md`](./ONTOLOGY.md) for the full schema and the per-field conflict rules.

## Architecture

```
┌─────────────┐   ┌───────────────────────┐   ┌─────────────┐
│ cmdb_adapter │   │ discovery_adapter     │   │ telemetry_  │
│ (static,     │   │ (re-scans the full    │   │ adapter     │
│  loads once) │   │  service topology     │   │ (frequent   │
│              │   │  every tick)          │   │  heartbeats)│
└──────┬──────┘   └───────────┬───────────┘   └──────┬──────┘
       │                      │                      │
       └──────────────┬───────┴──────────┬───────────┘
                       ▼                  ▼
            ┌───────────────────────────────────┐
            │     ReconciliationEngine          │
            │  (pure Python, no DB calls)        │
            │  - per-field conflict resolution   │
            │  - staleness detection             │
            │  - blast-radius / dependency BFS   │
            └────────────────┬──────────────────┘
                              │
                ┌─────────────┴─────────────┐
                ▼                           ▼
        ┌───────────────┐          ┌──────────────────┐
        │     Neo4j      │          │ FastAPI REST +    │
        │ (durable copy, │          │ WebSocket - reads  │
        │  real Cypher)  │          │ straight from the  │
        └───────────────┘          │ engine, not Neo4j   │
                                    └─────────┬─────────┘
                                              ▼
                                  ┌───────────────────────┐
                                  │ React/TypeScript       │
                                  │ dashboard (live graph) │
                                  └───────────────────────┘
```

The cmdb adapter loads once, at startup. The discovery and telemetry adapters run on a background loop (every few seconds), and every tick's observations get fed into the `ReconciliationEngine`, which is the one place that decides what the graph currently looks like. Every change gets pushed out over a WebSocket, so the dashboard updates without you refreshing the page, and mirrored into Neo4j so you can also explore it with real Cypher queries (see `backend/app/graph/queries.py` and the Neo4j Browser walkthrough below).

**Why the API reads from an in-memory engine instead of querying Neo4j directly:** the reconciliation engine already has to hold the full current state in memory to do conflict resolution - there's no extra cost to also serving reads from it, and it means the API and the blast-radius query don't depend on a database round-trip (or on Docker being installed at all - see "Running it locally"). Neo4j is still real and still gets the same data: it's the durable, Cypher-queryable copy, and it's also the natural next step if this ever needs to run as more than one backend process, since at that point the in-memory engine stops being a single source of truth and Neo4j would have to become the real one.

## How the reconciliation actually works

All of this lives in `backend/app/reconciliation/` and has zero imports of the Neo4j driver anywhere in it - that's what makes it possible to unit test every rule below without Docker running at all (see `backend/tests/test_reconciliation.py` and `test_impact.py`).

**1. Per-field conflict resolution.** Every property on a node has one rule that decides which source wins when two of them disagree (`backend/app/reconciliation/trust.py`):
- Structural/ownership fields (`region_id`, `datacenter_id`, `owner`, `name`) - the CMDB always wins once it has an opinion, though another source is allowed to fill the field in first if the CMDB hasn't reported yet.
- Everything else (`status`, `last_seen`, ...) - whichever source reported most recently wins. These are live-state fields where "what's true right now" is what matters.

**2. Staleness.** If no source has said anything about a given host within a configurable TTL (`staleness_ttl_seconds`, default 30s for this demo), that host is marked stale in the API response instead of silently showing you its last known state as if it were still current. Staleness is about *data freshness*, not health - a stale host might be perfectly fine, the graph just can't vouch for that right now.

**3. Dependency edges are a full re-snapshot, not a diff.** The discovery adapter reports its *entire* current view of the service dependency graph on every tick. If an edge it used to report is missing from the new tick, it explicitly reports that edge as gone (rather than the engine having to guess from silence), and the engine marks it inactive immediately. This is what lets the dashboard show a dependency genuinely disappearing - e.g. after a redeploy removes a call between two services - instead of only ever accumulating edges forever.

## What you can actually do with the graph once it's reconciled

The signature feature is the **blast-radius query**: `GET /api/impact/{node_id}`. Give it a host or a service, and it tells you:

- **downstream_impact** - everything that would be affected if this node went down (found by walking `DEPENDS_ON` / `RUNS_ON` edges backwards: "who requires this, directly or transitively?").
- **upstream_dependencies** - everything this node itself requires to be healthy (the same edges, walked forwards).

In the dashboard, click any node and hit "What breaks if this goes down?" - the affected nodes light up orange, and the things it depends on light up blue.

## Running it locally

You'll need Python 3.11+ and Node 18+. Docker is optional - the dashboard and API work fully without it (see below for what you lose without it).

**1. (Optional) Start Neo4j:**

```bash
cp .env.example .env     # only needed if you want to change the default password
docker compose up -d
```

This starts Neo4j with the Browser UI at `http://localhost:7474` and the Bolt port (what the backend connects to) at `7687`. If you skip this step entirely, the backend logs a warning on startup and keeps running perfectly well on the in-memory engine - you just won't be able to explore the graph with Neo4j Browser or raw Cypher.

**2. Start the backend:**

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate        # on macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

On startup, the backend loads the CMDB snapshot, runs one reconciliation tick so there's data immediately, and starts the background loop. Check `http://localhost:8000/api/health` - it reports whether Neo4j is actually reachable.

**3. Start the frontend:**

```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173`. You should see the graph render within a second or two, and watch it update live every few seconds as the simulated discovery/telemetry adapters report in.

## A walkthrough: watch a real incident happen

The telemetry adapter occasionally (and randomly) reports a host as unhealthy, the same way a real health-check failure would look. When that happens:

1. An `IncidentEvent` node appears, linked to the affected host, and it shows up in the "Recent incidents" list on the left of the dashboard.
2. Click the affected host, then click "What breaks if this goes down?"
3. Watch the downstream services light up orange - that's the actual blast radius, computed from the live graph, not guessed at.

You can also open Neo4j Browser at `http://localhost:7474` (if you started Docker) and run the equivalent query by hand - see `backend/app/graph/queries.py` for the exact Cypher:

```cypher
MATCH (start:Host {id: "host-001"})
MATCH path = (dependent)-[:RUNS_ON|DEPENDS_ON*1..6]->(start)
RETURN DISTINCT dependent.id AS node_id, labels(dependent)[0] AS label, length(path) AS hops
ORDER BY hops
```

## Running the tests

```bash
cd backend
pytest
```

These cover ontology validation, every branch of the per-field conflict rules described above (including "a field can be filled by a non-CMDB source first, but CMDB takes over once it reports"), staleness detection, and the blast-radius/dependency traversal in both directions on a small synthetic dependency graph. None of them require Neo4j or Docker to be running - the reconciliation and traversal logic is deliberately decoupled from the database so a bug in "is this a real match?" gets caught in milliseconds, not by debugging a full stack.

## What's simplified here, and what a larger production deployment would add

Being upfront about this, because pretending a side project is bigger than it is helps nobody:

- **The in-memory engine is the single source of truth**, and it's gone on restart (re-populated from the adapters on the next startup). A bigger deployment, especially one running more than one backend process, would need Neo4j (or another durable store) to be the actual source of truth instead of a mirror, with reads going through it directly or through a cache that's invalidated properly across instances.
- **The background polling loop runs in-process** with `asyncio`. At real scale, you'd want the discovery/telemetry ingestion running as separate workers reading off a message bus (Kafka, Kinesis, etc.) instead of one backend process polling everything on a timer.
- **The WebSocket broadcast is single-process.** If you ran multiple backend replicas behind a load balancer, a delta produced on one instance wouldn't reach clients connected to another, without adding a pub/sub layer in front of it.
- **No authentication/authorization** on the API or the Neo4j instance beyond the default local credentials - fine for a laptop, not fine for anything real.
- **No history.** The graph only reflects current state. A production system that needs to answer "why did the topology look different an hour ago" would need to version the graph, not just overwrite it on every tick.
- **Dependency confidence isn't scored.** Right now a `DEPENDS_ON` edge is simply present or absent, based on what discovery reported this tick. A more sophisticated system might track *how* a dependency was learned (declared in config vs. only ever observed in live traffic) and surface that as a confidence score, since an undeclared-but-observed coupling is useful information in its own right.

## License

MIT - see `LICENSE`.
