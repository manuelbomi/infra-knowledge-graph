"""
Unit tests for the pure reconciliation rules in app/ingest/rules.py.

These don't touch Neo4j at all -- that's the point. The decisions that
matter most (is this fact stale? how much do we trust this edge?) need to
be correct on their own, independent of whatever database we happen to
store the graph in.
"""

from datetime import datetime, timedelta, timezone

import pytest

from app.ingest import rules


def test_is_stale_returns_true_when_never_seen():
    assert rules.is_stale(None, datetime.now(timezone.utc), ttl_seconds=30) is True


def test_is_stale_returns_false_within_ttl():
    now = datetime.now(timezone.utc)
    last_seen = (now - timedelta(seconds=10)).isoformat()
    assert rules.is_stale(last_seen, now, ttl_seconds=30) is False


def test_is_stale_returns_true_past_ttl():
    now = datetime.now(timezone.utc)
    last_seen = (now - timedelta(seconds=60)).isoformat()
    assert rules.is_stale(last_seen, now, ttl_seconds=30) is True


def test_dependency_confidence_both_sources_agree():
    label, confidence = rules.dependency_confidence(declared=True, observed=True)
    assert confidence == 1.0
    assert "declared" in label and "observed" in label


def test_dependency_confidence_observed_only_is_undeclared_coupling():
    label, confidence = rules.dependency_confidence(declared=False, observed=True)
    assert confidence == pytest.approx(0.7)
    assert "undeclared" in label


def test_dependency_confidence_declared_only_is_unconfirmed():
    label, confidence = rules.dependency_confidence(declared=True, observed=False)
    assert confidence == pytest.approx(0.3)
    assert "unconfirmed" in label


def test_dependency_confidence_requires_at_least_one_source():
    with pytest.raises(ValueError):
        rules.dependency_confidence(declared=False, observed=False)


def test_classify_health_down_beats_staleness():
    assert rules.classify_health("down", stale=True) == "unhealthy"


def test_classify_health_stale_without_down_is_unknown():
    assert rules.classify_health("up", stale=True) == "unknown (no recent heartbeat)"


def test_classify_health_up_and_fresh_is_healthy():
    assert rules.classify_health("up", stale=False) == "healthy"
