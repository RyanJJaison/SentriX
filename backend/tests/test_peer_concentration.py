from app.services.traffic_correlation import peer_concentration_score
from tests.conftest import make_event


def test_no_events():
    assert peer_concentration_score([]) == 0.0


def test_single_peer_is_maximally_concentrated():
    events = [make_event(peer_id="peer-01", offset_ms=i) for i in range(5)]
    assert peer_concentration_score(events) == 1.0


def test_even_distribution_scores_low():
    events = [make_event(peer_id=f"peer-{i:02d}", offset_ms=i * 10) for i in range(8)]
    assert peer_concentration_score(events) < 0.3


def test_dominant_peer_scores_higher_than_even():
    even = [make_event(peer_id=f"p{i}", offset_ms=i) for i in range(6)]
    concentrated = (
        [make_event(peer_id="p0", offset_ms=i) for i in range(8)]
        + [make_event(peer_id="p1", offset_ms=100)]
        + [make_event(peer_id="p2", offset_ms=200)]
    )
    assert peer_concentration_score(concentrated) > peer_concentration_score(even)
    assert 0.0 <= peer_concentration_score(concentrated) <= 1.0


def test_deterministic():
    events = [make_event(peer_id=f"p{i % 3}", offset_ms=i) for i in range(12)]
    assert peer_concentration_score(events) == peer_concentration_score(list(reversed(events)))
