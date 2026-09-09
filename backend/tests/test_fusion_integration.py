from app.scheduler import rescoring
from app.services import risk_service, traffic_correlation


def test_address_risk_stays_in_range_and_deterministic():
    a = risk_service._compute_address_risk("1SomeTestAddress")
    b = risk_service._compute_address_risk("1SomeTestAddress")
    assert 0.0 <= a.risk_score <= 1.0
    assert 0.0 <= a.contributing_factors.traffic_anomaly_score <= 1.0
    # Same address -> identical fused score and factors. `last_updated` is the
    # wall-clock instant of each computation, so it is deliberately excluded:
    # comparing it only ever "passed" because Windows' 15.6 ms clock tick is
    # coarser than two back-to-back calls.
    assert a.model_dump(exclude={"last_updated"}) == b.model_dump(exclude={"last_updated"})


def test_traffic_component_comes_from_the_engine_when_seeded():
    traffic_correlation.ensure_seeded()
    score = traffic_correlation.get_address_traffic_anomaly("1SomeTestAddress")
    assert score is not None and 0.0 <= score <= 1.0

    intel = traffic_correlation.get_address_traffic_intel("1SomeTestAddress")
    assert set(intel) == {"traffic_anomaly_score", "traffic_features", "traffic_factors"}
    assert 0.0 <= intel["traffic_anomaly_score"] <= 1.0
    assert len(intel["traffic_factors"]) == 4


def test_falls_back_when_no_traffic_data(monkeypatch):
    monkeypatch.setattr(traffic_correlation, "_demo_mode", lambda: False)
    traffic_correlation.engine.clear()
    traffic_correlation._seeded = True  # block re-seeding

    assert traffic_correlation.get_address_traffic_anomaly("1SomeTestAddress") is None
    # risk service must still produce a valid score via its own fallback
    result = risk_service._compute_address_risk("1SomeTestAddress")
    assert 0.0 <= result.risk_score <= 1.0


def test_refresh_and_rescoring_cycle_do_not_raise():
    summary = traffic_correlation.refresh()
    assert set(summary) == {"events", "transactions", "anomalies", "top_score"}

    # empty window must be a safe no-op
    traffic_correlation.engine.clear()
    traffic_correlation._seeded = True
    monkey = traffic_correlation._demo_mode
    try:
        traffic_correlation._demo_mode = lambda: False  # type: ignore[assignment]
        empty = traffic_correlation.engine.refresh()
        assert empty["anomalies"] == 0 and empty["events"] == 0
    finally:
        traffic_correlation._demo_mode = monkey  # type: ignore[assignment]

    # full scheduler cycle stays green
    rescoring.run_rescoring_cycle()
