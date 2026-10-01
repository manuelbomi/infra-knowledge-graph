import pytest

from app.ontology.schema import NodeLabel, constraint_statements, validate_node_properties


def test_validate_node_properties_passes_with_all_required_fields():
    validate_node_properties(NodeLabel.HOST, {"id": "host-1", "hostname": "host-1.internal"})


def test_validate_node_properties_rejects_missing_fields():
    with pytest.raises(ValueError, match="missing required properties"):
        validate_node_properties(NodeLabel.HOST, {"id": "host-1"})


def test_constraint_statements_cover_every_node_label():
    statements = constraint_statements()
    assert len(statements) == len(list(NodeLabel))
    for label in NodeLabel:
        assert any(label.value in statement for statement in statements)
