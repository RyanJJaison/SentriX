from app.services.traffic_correlation import broadcast_timing_score, build_propagation
from tests.conftest import make_event


def _prop(events):
    return build_propagation("tx-test", events)


def test_empty_and_single_peer():
    assert broadcast_timing_score(build_propagation("tx", [])) == 0.0
    one = _prop([make_event(peer_id="peer-01", offset_ms=0)])
    assert 0.0 <= broadcast_timing_score(one) <= 1.0


def test_even_spread_scores_low():
    events = [make_event(peer_id=f"peer-{i:02d}", offset_ms=i * 150) for i in range(6)]
    prop = _prop(events)
    assert prop.peer_count == 6
    assert prop.propagation_duration_ms == 750.0
    assert broadcast_timing_score(prop) < 0.35


def test_compressed_propagation_scores_higher_than_even():
    even = _prop([make_event(peer_id=f"p{i}", offset_ms=i * 150) for i in range(6)])
    compressed = _prop([make_event(peer_id=f"p{i}", offset_ms=i * 5) for i in range(6)])
    assert broadcast_timing_score(compressed) > broadcast_timing_score(even)
    assert 0.0 <= broadcast_timing_score(compressed) <= 1.0


def test_propagation_summary_stats():
    events = [make_event(peer_id=f"p{i}", offset_ms=d) for i, d in enumerate([0, 10, 20, 900])]
    prop = _prop(events)
    assert prop.peer_count == 4
    assert prop.first_seen is not None and prop.last_seen is not None
    assert prop.p95_delay_ms >= prop.median_delay_ms
    assert [p.peer_id for p in prop.peers] == ["p0", "p1", "p2", "p3"]


def test_deterministic():
    events = [make_event(peer_id=f"p{i}", offset_ms=i * 7) for i in range(5)]
    a = broadcast_timing_score(_prop(events))
    b = broadcast_timing_score(_prop(list(reversed(events))))
    assert a == b
