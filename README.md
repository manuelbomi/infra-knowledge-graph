# Infrastructure Knowledge Graph

A live, queryable graph of "what's running where" for a piece of
infrastructure -- regions, data centers, hosts, services, and how they all
depend on each other -- built on Neo4j, with a dashboard that updates in
real time as the infrastructure changes.

## The problem this solves

If you've worked on any infrastructure or platform team, you've run into this:
nobody has one single, trustworthy answer to "what's actually running right
now, and what depends on what?"

Usually the truth is spread across several systems that don't agree with each
other:

- Your **CMDB** (configuration management database) says what *should* exist
  -- but it's often stale, because keeping it perfectly in sync with reality
  is nobody's full-time job.
- A **service discovery** feed (a service mesh, an agent, whatever) tells you
  what's *actually* talking to what right now -- but it can miss things for a
  few seconds, and it sometimes finds dependencies nobody documented.
- A **telemetry/health-check** feed tells you what's healthy -- but a
  heartbeat going quiet doesn't necessarily mean something is down, it might
  just mean you haven't heard from it recently.

None of these three sources is "the truth" on its own. The interesting
engineering problem isn't storing a graph -- Neo4j does that part for you.
The interesting problem is **reconciling** three sources that update at
different speeds and sometimes flatly disagree, into one graph you can
actually trust enough to ask it questions like "if this host goes down, what
breaks?"

That reconciliation logic is the core of this project.

## What a knowledge graph / operational ontology actually means here

Two terms that sound more intimidating than they are:

- **Knowledge graph**: just a graph database (nodes + relationships) where the
  nodes and relationships represent real things you care about (hosts,
  services, incidents) instead of generic rows in a table. The advantage over
  a normal database is that questions like "what depends on what, transitively,
  five hops away?" are a single query instead of a pile of joins.
- **Operational ontology**: the fixed vocabulary of node types and
  relationship types everything has to fit into. Before you can reconcile
  three different sources, they all have to agree on what a "Host" is and
  what "DEPENDS_ON" means. See [`ONTOLOGY.md`](./ONTOLOGY.md) for the full
  schema.

## Architecture

```
┌──────────────┐   ┌──────────────────┐   ┌──────────────────┐
│  CMDB source  │   │ Discovery source │   │ Telemetry source │
│ (static, rare │   │ (what's actually │   │ (health pings,    │
│  changes)     │   │  running now)    │   │  every few secs)  │
└───────┬──────┘   └─────────┬────────┘   └─────────┬────────┘
        │                    │                      │
        └──────────────┬─────┴──────────┬───────────┘
                        ▼                ▼
                 ┌─────────────────────────────┐
                 │        Reconciler           │
                 │  - staleness / TTL rules     │
                 │  - confidence scoring for    │
                 │    conflicting dependencies  │
                 │  - idempotent upserts        │
                 └───────────────┬─────────────┘
                                 ▼
                         ┌───────────────┐
                         │     Neo4j     │
                         └───────┬───────┘
                                 ▼
                  ┌───────────────────────────┐
                  │  FastAPI (REST + WebSocket) │
                  └───────────────┬───────────┘
                                 ▼
                    ┌───────────────────────┐
                    │ React/TypeScript       │
                    │ dashboard (live graph) │
                    └───────────────────────┘
```

The CMDB source loads once, at startup. The discovery and telemetry sources
get polled on a loop (every few seconds) by a background task, and every
cycle's results get merged into the graph by the reconciler. Every change the
reconciler makes gets pushed out over a WebSocket, so the dashboard updates
without you refreshing the page.

## How the reconciliation actually works

Two rules do most of the work. Both are implemented as small, plain Python
functions with no database or network code in them at all (see
`backend/app/ingest/rules.py`), specifically so they're easy to unit test and
easy to reason about on their own.

**1. Staleness.** A `RUNS_ON` edge (service X runs on host Y) that the CMDB
declared but that discovery hasn't reconfirmed within the last 30 seconds gets
marked `stale` instead of `active`. This matters because without it, the
graph would just show you a frozen snapshot of what the CMDB thinks should be
true forever -- even long after it stopped being true. Marking things stale is
how the graph stays honest about what it actually knows *right now* versus
what it was told once.

**2. Conflicting dependency claims.** The CMDB might declare that `checkout-
service` depends on `payment-service`. Discovery might observe a completely
different, undeclared dependency -- say, `search-service` quietly calling
`inventory-service`, something nobody ever put in an architecture diagram.
Instead of picking one source and throwing the other away, every `DEPENDS_ON`
edge gets a `confidence` score and a `source_label` describing exactly why:

| Declared? | Observed? | Confidence | Label |
|---|---|---|---|
| yes | yes | 1.0 | `declared+observed` |
| no | yes | 0.7 | `observed-only (undeclared)` |
| yes | no | 0.3 | `declared-only (unconfirmed)` |

An `observed-only` edge is genuinely useful information -- it's an
undocumented coupling between two services that someone should probably go
write down. Throwing it away because it "wasn't declared" would be throwing
away the whole point of running a discovery feed in the first place.

## What you can actually do with the graph once it's reconciled

The most concrete payoff is the **blast-radius query**:
`GET /api/impact/{node_id}`. Give it a host or a service, and it tells you:

- **downstream_impact**: everything that would be affected if this node went
  down (found by following `DEPENDS_ON` / `RUNS_ON` edges backwards --
  "who requires this, directly or transitively?")
- **upstream_dependencies**: everything this node itself requires to be
  healthy (the same edges, followed forwards)

In the dashboard, click any node and hit "What breaks if this goes down?" --
the affected nodes light up orange, and the things it depends on light up
blue.

## Running it locally

You'll need Docker, Python 3.11+, and Node 18+.

**1. Start Neo4j:**

```bash
docker compose up -d
```

This starts Neo4j with the Browser UI at http://localhost:7474 and the Bolt
port (what the backend connects to) at `7687`. Default credentials are
`neo4j` / `localdevpassword` (see `docker-compose.yml` if you want to change
them -- just make sure `backend/.env` matches).

**2. Start the backend:**

```bash
cd backend
python -m venv .venv
.venv/Scripts/activate   # on macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env     # only needed if you changed the Neo4j password above
uvicorn app.main:app --reload
```

On startup, the backend creates the Neo4j constraints, loads the CMDB
snapshot, and starts the background reconciliation loop. You should be able
to hit `http://localhost:8000/api/health` and see `"neo4j_reachable": true`.

**3. Start the frontend:**

```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173`. You should see the graph render within a
second or two, and watch it update live every few seconds as the simulated
discovery/telemetry feeds report in.

## A walkthrough: watch a real incident happen

The telemetry source occasionally (and randomly) takes a host or service
down for a few cycles, the same way a real outage would look. When that
happens:

1. The node's ring turns solid red in the graph (unhealthy), and it shows up
   in the "Recent incidents" list on the left.
2. Click it, then click "What breaks if this goes down?"
3. Watch the downstream services light up orange -- that's your actual blast
   radius, computed from the graph, not guessed at.

You can also just open the Neo4j Browser at `http://localhost:7474` and run
the same query by hand:

```cypher
MATCH (impacted)-[:DEPENDS_ON|RUNS_ON*1..6]->(target {id: "payment-service"})
RETURN DISTINCT impacted.id, labels(impacted)
```

## Running the tests

```bash
cd backend
pytest
```

The tests cover the ontology validation, the CMDB data generator, and --most
importantly-- every branch of the staleness and confidence-scoring rules
described above. They don't require Neo4j to be running; they test the
decision logic in isolation on purpose, so a bug in "is this fact stale?"
gets caught in milliseconds instead of requiring a full stack to debug.

## What's simplified here, and what a larger production deployment would add

Being upfront about this, because pretending a side project is bigger than it
is helps nobody:

- **State for reconciliation watermarks** (when was this last seen?) lives in
  process memory right now, not in a durable store. A restart forgets it,
  which just means everything briefly looks stale until the next discovery
  cycle confirms it again. A bigger deployment would persist this.
- **The background polling loop runs in-process** with `asyncio`. At real
  scale, you'd want the discovery/telemetry ingestion running as separate
  workers reading off a message bus (Kafka, Kinesis, etc.) instead of one
  backend process doing everything on a timer.
- **The WebSocket broadcast is single-process.** If you ran multiple backend
  replicas behind a load balancer, a delta produced on one instance wouldn't
  reach clients connected to another, without adding a pub/sub layer.
- **No authentication/authorization** on the API or the Neo4j instance beyond
  the default local credentials -- fine for a laptop, not fine for anything
  real.
- **No graph versioning or audit trail.** Right now the graph only reflects
  current state. A production system doing "why did the topology look
  different an hour ago" would need to track history, not just overwrite it.
