from datetime import datetime, timedelta

from app.ontology.schema import NodeLabel, RelType
from app.reconciliation.engine import ReconciliationEngine
from app.reconciliation.models import EdgeObservation, NodeObservation

T0 = datetime(2024, 1, 1, 12, 0, 0)


def test_cmdb_wins_region_even_if_reported_later_by_another_source():
    engine = ReconciliationEngine()
    engine.apply_node_observation(
        NodeObservation(NodeLabel.HOST, "h1", {"id": "h1", "hostname": "web-01", "region_id": "us-east-1"}, "cmdb", T0)
    )
    # A later observation from telemetry tries to claim a different region -
    # telemetry has no business setting ownership/structural fields, so this
    # must not overwrite the cmdb value.
    engine.apply_node_observation(
        NodeObservation(NodeLabel.HOST, "h1", {"region_id": "us-west-2"}, "telemetry", T0 + timedelta(hours=1))
    )
    assert engine.nodes[(NodeLabel.HOST.value, "h1")].properties["region_id"] == "us-east-1"


def test_most_recent_source_wins_for_status():
    engine = ReconciliationEngine()
    engine.apply_node_observation(
        NodeObservation(NodeLabel.HOST, "h1", {"id": "h1", "hostname": "web-01", "status": "healthy"}, "cmdb", T0)
    )
    engine.apply_node_observation(
        NodeObservation(NodeLabel.HOST, "h1", {"status": "degraded"}, "telemetry", T0 + timedelta(minutes=5))
    )
    assert engine.nodes[(NodeLabel.HOST.value, "h1")].properties["status"] == "degraded"

    # An older observation arriving out of order should not win.
    engine.apply_node_observation(
        NodeObservation(NodeLabel.HOST, "h1", {"status": "healthy"}, "cmdb", T0 + timedelta(minutes=1))
    )
    assert engine.nodes[(NodeLabel.HOST.value, "h1")].properties["status"] == "degraded"


def test_non_cmdb_source_can_fill_a_gap_but_cmdb_later_takes_over():
    engine = ReconciliationEngine()
    engine.apply_node_observation(
        NodeObservation(NodeLabel.HOST, "h1", {"id": "h1", "hostname": "web-01"}, "telemetry", T0)
    )
    # cmdb hasn't reported an owner yet, so a discovery-style source filling
    # the gap is accepted rather than left blank.
    engine.apply_node_observation(
        NodeObservation(NodeLabel.HOST, "h1", {"owner": "unknown"}, "service_mesh_discovery", T0 + timedelta(minutes=10))
    )
    assert engine.nodes[(NodeLabel.HOST.value, "h1")].properties["owner"] == "unknown"

    # Once cmdb actually reports, it takes over even though it reports later.
    engine.apply_node_observation(
        NodeObservation(NodeLabel.HOST, "h1", {"owner": "platform-team"}, "cmdb", T0 + timedelta(hours=1))
    )
    assert engine.nodes[(NodeLabel.HOST.value, "h1")].properties["owner"] == "platform-team"


def test_field_change_on_an_existing_node_emits_an_event():
    engine = ReconciliationEngine()
    engine.apply_node_observation(
        NodeObservation(NodeLabel.HOST, "h1", {"id": "h1", "hostname": "web-01", "status": "healthy"}, "cmdb", T0)
    )
    events = engine.apply_node_observation(
        NodeObservation(NodeLabel.HOST, "h1", {"status": "unhealthy"}, "telemetry", T0 + timedelta(minutes=1))
    )
    assert len(events) == 1
    assert events[0].kind == "node_upserted"
    assert events[0].detail["properties"]["status"] == "unhealthy"


def test_reconfirming_the_same_value_emits_no_event():
    engine = ReconciliationEngine()
    engine.apply_node_observation(
        NodeObservation(NodeLabel.HOST, "h1", {"id": "h1", "hostname": "web-01", "status": "healthy"}, "cmdb", T0)
    )
    events = engine.apply_node_observation(
        NodeObservation(NodeLabel.HOST, "h1", {"status": "healthy"}, "telemetry", T0 + timedelta(minutes=1))
    )
    assert events == []


def test_edge_removal_marks_inactive():
    engine = ReconciliationEngine()
    engine.apply_edge_observation(EdgeObservation(RelType.DEPENDS_ON, "svc-a", "svc-b", "service_mesh_discovery", T0))
    key = (RelType.DEPENDS_ON.value, "svc-a", "svc-b")
    assert engine.edges[key].active is True

    engine.apply_edge_observation(
        EdgeObservation(RelType.DEPENDS_ON, "svc-a", "svc-b", "service_mesh_discovery", T0 + timedelta(minutes=1), present=False)
    )
    assert engine.edges[key].active is False
    assert engine.all_active_edges() == []


def test_stale_host_detected_after_ttl():
    engine = ReconciliationEngine()
    engine.apply_node_observation(
        NodeObservation(NodeLabel.HOST, "h1", {"id": "h1", "hostname": "web-01"}, "telemetry", T0)
    )
    now = T0 + timedelta(seconds=120)
    assert engine.stale_host_ids(now, ttl_seconds=60) == ["h1"]
    assert engine.stale_host_ids(now, ttl_seconds=300) == []
