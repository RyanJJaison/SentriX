import pytest
from pydantic import ValidationError

from app.models.traffic import CorrelationResult, TrafficEvent, is_safe_id
from tests.conftest import make_event


def test_is_safe_id():
    assert is_safe_id("tx-normal-001")
    assert is_safe_id("10.0.0.1:8333")
    assert is_safe_id("a" * 128)
    assert not is_safe_id("")
    assert not is_safe_id("a" * 129)
    assert not is_safe_id("../etc/passwd")
    assert not is_safe_id("rm -rf /")
    assert not is_safe_id("tx;drop")


def test_traffic_event_minimal_and_optional_fields():
    ev = TrafficEvent(timestamp="2026-01-01T00:00:00Z", peer_id="peer-01")
    assert ev.protocol == "bitcoin"
    assert ev.txid is None and ev.src_ip is None and ev.raw_metadata == {}


def test_traffic_event_rejects_unsafe_ids():
    with pytest.raises(ValidationError):
        make_event(peer_id="peer 01; ls")
    with pytest.raises(ValidationError):
        make_event(txid="../../secret")


def test_correlation_result_shape():
    r = CorrelationResult(
        entity_id="tx-x", anomaly_score=0.5, confidence=0.8, event_count=3, peer_count=2
    )
    assert r.entity_type == "transaction"
    assert r.features == {} and r.factors == []
