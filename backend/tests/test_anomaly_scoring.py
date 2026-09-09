from datetime import datetime, timezone

from app.capture.demo_fixtures import build_demo_events
from app.services.traffic_correlation import (
    TrafficCorrelationEngine,
    confidence_from_evidence,
    score_from_features,
)
from tests.conftest import make_event

FEATURES_HIGH = {
    "broadcast_timing": 0.71,
    "burst_activity": 0.91,
    "peer_concentration": 0.76,
    "propagation_irregularity": 0.84,
}


def test_weighted_score_and_factor_bookkeeping():
    score, factors = score_from_features(FEATURES_HIGH, peer_count=8)
    assert 0.0 <= score <= 1.0
    assert len(factors) == 4
    assert sum(f.contribution for f in factors) == score or abs(sum(f.contribution for f in factors) - score) < 1e-3
    assert factors == sorted(factors, key=lambda f: f.contribution, reverse=True)
    assert abs(sum(f.weight for f in factors) - 1.0) < 1e-6
    assert all(f.explanation for f in factors)


def test_zero_features_zero_score():
    score, _ = score_from_features({k: 0.0 for k in FEATURES_HIGH}, peer_count=1)
    assert score == 0.0


def test_confidence_monotonic_and_bounded():
    assert confidence_from_evidence(0, 0) < confidence_from_evidence(50, 10)
    for ec, pc in [(0, 0), (5, 2), (100, 50)]:
        assert 0.0 <= confidence_from_evidence(ec, pc) <= 1.0


def test_engine_correlate_transaction_on_custom_events():
    eng = TrafficCorrelationEngine(window_seconds=3600)
    eng.ingest([make_event(peer_id=f"p{i}", txid="tx-a", offset_ms=i * 100) for i in range(6)])
    r = eng.correlate_transaction("tx-a")
    assert r is not None
    assert r.entity_id == "tx-a" and r.entity_type == "transaction"
    assert set(r.features) == set(FEATURES_HIGH)
    assert 0.0 <= r.anomaly_score <= 1.0
    assert r.propagation is not None and r.propagation.peer_count == 6
    assert eng.correlate_transaction("tx-missing") is None


def test_demo_fixture_relative_ordering_and_determinism():
    def scores():
        eng = TrafficCorrelationEngine(window_seconds=3600)
        eng.ingest(build_demo_events(datetime(2026, 1, 1, tzinfo=timezone.utc)))
        return {r.entity_id: r.anomaly_score for r in eng.detect_anomalies()}

    s1, s2 = scores(), scores()
    assert s1 == s2  # deterministic for identical input
    for v in s1.values():
        assert 0.0 <= v <= 1.0
    assert s1["tx-suspicious-001"] > s1["tx-normal-001"]
    assert s1["tx-burst-001"] > s1["tx-normal-001"]
    assert s1["tx-concentration-001"] > s1["tx-normal-001"]
