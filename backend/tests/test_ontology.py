import pytest

from app.ontology.schema import NodeLabel, validate_node_properties


def test_valid_host_passes():
    validate_node_properties(NodeLabel.HOST, {"id": "h1", "hostname": "web-01"})


def test_host_missing_hostname_raises():
    with pytest.raises(ValueError, match="hostname"):
        validate_node_properties(NodeLabel.HOST, {"id": "h1"})


def test_datacenter_missing_region_raises():
    with pytest.raises(ValueError, match="region_id"):
        validate_node_properties(NodeLabel.DATA_CENTER, {"id": "dc1", "name": "dc-1"})


def test_incident_event_requires_started_at():
    with pytest.raises(ValueError):
        validate_node_properties(NodeLabel.INCIDENT_EVENT, {"id": "inc1"})
