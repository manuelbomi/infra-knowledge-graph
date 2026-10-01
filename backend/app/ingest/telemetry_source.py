"""
Simulates a health-check / heartbeat feed (think: a Prometheus blackbox
exporter or an agent-based health check hitting every host and service).

This is the fastest-moving of the three sources -- it's meant to be polled
every few seconds, which is why it's the one that drives the "stale" /
"unhealthy" coloring in the frontend. A host that hasn't sent a heartbeat
recently is just as suspicious as one that explicitly reported "down".

State (which hosts/services are currently unhealthy) is kept in this
module between calls so an outage looks realistic: once something goes
down, it tends to stay down for a few cycles before recovering, instead of
flickering randomly every call.
"""

import random

from app.ingest.cmdb_source import get_cmdb_snapshot

# id -> number of remaining cycles this entity should stay unhealthy
_unhealthy_countdown: dict[str, int] = {}

GO_DOWN_PROBABILITY = 0.04
OUTAGE_LENGTH_CYCLES = (2, 5)


def _roll_status(entity_id: str) -> tuple[str, float]:
    """Decide up/down + latency for one entity, with simple outage persistence."""
    if _unhealthy_countdown.get(entity_id, 0) > 0:
        _unhealthy_countdown[entity_id] -= 1
        return "down", 0.0

    if random.random() < GO_DOWN_PROBABILITY:
        _unhealthy_countdown[entity_id] = random.randint(*OUTAGE_LENGTH_CYCLES)
        return "down", 0.0

    # Healthy latency: mostly fast, with occasional slow outliers.
    latency_ms = round(random.gauss(40, 12) if random.random() > 0.08 else random.uniform(200, 400), 1)
    return "up", max(latency_ms, 1.0)


def poll_telemetry() -> dict:
    """Return current up/down status + latency for every host and service."""
    snapshot = get_cmdb_snapshot()

    host_status = {}
    for host in snapshot["hosts"]:
        status, latency = _roll_status(host["id"])
        host_status[host["id"]] = {"status": status, "latency_ms": latency}

    service_status = {}
    for service in snapshot["services"]:
        status, latency = _roll_status(service["id"])
        service_status[service["id"]] = {"status": status, "latency_ms": latency}

    return {"host_status": host_status, "service_status": service_status}
