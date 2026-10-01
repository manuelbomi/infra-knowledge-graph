"""
Wires the three adapters into the reconciliation engine and runs them on a
background interval. This is the only place that knows about all three
sources at once - each adapter module only knows its own source.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from app.reconciliation.engine import ReconciliationEngine
from app.reconciliation.models import ChangeEvent

from . import cmdb_adapter
from .discovery_adapter import DiscoveryAdapter
from .telemetry_adapter import TelemetryAdapter

logger = logging.getLogger(__name__)

OnChange = Callable[[list[ChangeEvent]], Awaitable[None]]


class IngestionOrchestrator:
    def __init__(self, engine: ReconciliationEngine) -> None:
        self.engine = engine
        self.discovery = DiscoveryAdapter()
        self.telemetry = TelemetryAdapter()
        self._cmdb_loaded = False
        self.tick_count = 0

    def run_once(self, now: datetime | None = None) -> list[ChangeEvent]:
        now = now or datetime.now(UTC)
        events: list[ChangeEvent] = []

        if not self._cmdb_loaded:
            for obs in cmdb_adapter.snapshot(now):
                events.extend(self.engine.apply_node_observation(obs))
            self._cmdb_loaded = True

        discovery_nodes, discovery_edges = self.discovery.tick(now)
        for obs in discovery_nodes:
            events.extend(self.engine.apply_node_observation(obs))
        for obs in discovery_edges:
            events.extend(self.engine.apply_edge_observation(obs))

        telemetry_nodes, telemetry_edges = self.telemetry.tick(now)
        for obs in telemetry_nodes:
            events.extend(self.engine.apply_node_observation(obs))
        for obs in telemetry_edges:
            events.extend(self.engine.apply_edge_observation(obs))

        self.tick_count += 1
        return events

    async def run_forever(self, interval_seconds: float, on_change: OnChange) -> None:
        while True:
            try:
                events = self.run_once()
                if events:
                    await on_change(events)
            except Exception:  # noqa: BLE001 - a bad tick should never kill the whole background loop
                logger.exception("ingestion tick failed")
            await asyncio.sleep(interval_seconds)
