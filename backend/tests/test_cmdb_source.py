from app.ingest.cmdb_source import get_cmdb_snapshot


def test_snapshot_is_deterministic_across_calls():
    first = get_cmdb_snapshot()
    second = get_cmdb_snapshot()
    assert first == second


def test_every_declared_runs_on_references_a_real_service_and_host():
    snapshot = get_cmdb_snapshot()
    host_ids = {h["id"] for h in snapshot["hosts"]}
    service_ids = {s["id"] for s in snapshot["services"]}

    for service_id, host_id in snapshot["declared_runs_on"]:
        assert service_id in service_ids
        assert host_id in host_ids


def test_every_declared_dependency_references_real_services():
    snapshot = get_cmdb_snapshot()
    service_ids = {s["id"] for s in snapshot["services"]}

    for service_id, depends_on_id in snapshot["declared_depends_on"]:
        assert service_id in service_ids
        assert depends_on_id in service_ids
        assert service_id != depends_on_id
