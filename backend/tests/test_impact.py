from datetime import datetime

from app.ontology.schema import NodeLabel, RelType
from app.reconciliation.engine import ReconciliationEngine
from app.reconciliation.models import EdgeObservation, NodeObservation

T0 = datetime(2024, 1, 1, 12, 0, 0)


def _host(engine, host_id):
    engine.apply_node_observation(NodeObservation(NodeLabel.HOST, host_id, {"id": host_id, "hostname": host_id}, "cmdb", T0))


def _service(engine, svc_id):
    engine.apply_node_observation(NodeObservation(NodeLabel.SERVICE, svc_id, {"id": svc_id, "name": svc_id}, "service_mesh_discovery", T0))


def _build_sample_graph() -> ReconciliationEngine:
    """
    api -> RUNS_ON -> host-1
    api -> DEPENDS_ON -> checkout
    checkout -> RUNS_ON -> host-2
    frontend -> DEPENDS_ON -> api
    unrelated -> RUNS_ON -> host-3   (not connected to anything above)
    """
    engine = ReconciliationEngine()
    for host_id in ["host-1", "host-2", "host-3"]:
        _host(engine, host_id)
    for svc_id in ["api", "checkout", "frontend", "unrelated"]:
        _service(engine, svc_id)

    engine.apply_edge_observation(EdgeObservation(RelType.RUNS_ON, "api", "host-1", "service_mesh_discovery", T0))
    engine.apply_edge_observation(EdgeObservation(RelType.DEPENDS_ON, "api", "checkout", "service_mesh_discovery", T0))
    engine.apply_edge_observation(EdgeObservation(RelType.RUNS_ON, "checkout", "host-2", "service_mesh_discovery", T0))
    engine.apply_edge_observation(EdgeObservation(RelType.DEPENDS_ON, "frontend", "api", "service_mesh_discovery", T0))
    engine.apply_edge_observation(EdgeObservation(RelType.RUNS_ON, "unrelated", "host-3", "service_mesh_discovery", T0))
    return engine


def test_host_failure_affects_direct_and_transitive_dependents():
    engine = _build_sample_graph()
    impacted = {item["node_id"] for item in engine.impact(NodeLabel.HOST, "host-1")}
    assert impacted == {"api", "frontend"}


def test_unrelated_host_has_no_impact_outside_its_own_chain():
    engine = _build_sample_graph()
    impacted = {item["node_id"] for item in engine.impact(NodeLabel.HOST, "host-3")}
    assert impacted == {"unrelated"}


def test_hop_distance_increases_with_each_transitive_level():
    engine = _build_sample_graph()
    by_id = {item["node_id"]: item["hops"] for item in engine.impact(NodeLabel.HOST, "host-1")}
    assert by_id["api"] == 1
    assert by_id["frontend"] == 2


def test_dependencies_is_the_forward_direction_of_impact():
    engine = _build_sample_graph()
    deps = {item["node_id"] for item in engine.dependencies(NodeLabel.SERVICE, "api")}
    # api runs on host-1 and depends on checkout, which in turn depends on host-2.
    assert deps == {"host-1", "checkout", "host-2"}


def test_leaf_service_has_no_dependencies():
    engine = _build_sample_graph()
    assert engine.dependencies(NodeLabel.SERVICE, "unrelated") == [{"label": "Host", "node_id": "host-3", "hops": 1}]


def test_inactive_edge_is_excluded_from_blast_radius():
    engine = _build_sample_graph()
    # The dependency graph says frontend depends on api, but discovery then
    # reports that edge is gone (e.g. frontend got refactored) - the old
    # relationship should stop affecting the blast radius immediately.
    engine.apply_edge_observation(
        EdgeObservation(RelType.DEPENDS_ON, "frontend", "api", "service_mesh_discovery", T0, present=False)
    )
    impacted = {item["node_id"] for item in engine.impact(NodeLabel.HOST, "host-1")}
    assert impacted == {"api"}
