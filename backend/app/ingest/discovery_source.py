"""
Simulates a service-mesh discovery feed (think: Istio/Envoy telemetry, or an
eBPF-based connection tracker).

Unlike the CMDB, this source tells you what's *actually* talking to what,
right now. It's noisy on purpose:

  * Most of the time it re-confirms what the CMDB declared.
  * Sometimes it misses a declared service-to-host placement for a cycle
    (simulating a scrape that didn't catch it, or the service briefly not
    serving traffic) -- this is what drives the staleness logic in
    reconciler.py.
  * Occasionally it reports a dependency the CMDB never declared at all.
    This happens constantly in real systems: someone adds a call to another
    service and never updates the architecture diagram. Finding these
    undeclared dependencies is one of the main reasons to run discovery in
    the first place.
"""

import random

from app.ingest.cmdb_source import get_cmdb_snapshot

# A dependency nobody declared in the CMDB but that discovery keeps seeing.
# This is deliberately "surprising" so the dashboard has something
# interesting to show under reconciliation conflicts.
UNDECLARED_DEPENDENCY = ("search-service", "inventory-service")

MISS_PROBABILITY = 0.12  # chance a declared RUNS_ON isn't observed this cycle


def poll_discovery() -> dict:
    """Return what the discovery feed currently observes.

    Returns:
        observed_runs_on: list of (service_id, host_id) seen serving traffic now.
        observed_depends_on: list of (service_id, depended_on_service_id) seen now.
    """
    snapshot = get_cmdb_snapshot()

    observed_runs_on = [
        pair for pair in snapshot["declared_runs_on"] if random.random() > MISS_PROBABILITY
    ]

    observed_depends_on = list(snapshot["declared_depends_on"])
    # Most cycles, discovery also notices the undeclared call.
    if random.random() > 0.15:
        observed_depends_on.append(UNDECLARED_DEPENDENCY)

    return {
        "observed_runs_on": observed_runs_on,
        "observed_depends_on": observed_depends_on,
    }
