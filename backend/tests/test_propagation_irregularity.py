from app.services.traffic_correlation import (
    broadcast_timing_score,
    build_propagation,
    peer_concentration_score,
    propagation_irregularity_score,
)
from tests.conftest import make_event


def _score(events):
    prop = build_propagation("tx-test", events)
    timing = broadcast_timing_score(prop)
    conc = peer_concentration_score(events)
    return propagation_irregularity_score(events, prop, timing, conc)


def test_normal_propagation_scores_low():
    events = [make_event(peer_id=f"p{i}", offset_ms=i * 140) for i in range(6)]
    assert _score(events) < 0.3


def test_repeats_and_uneven_gaps_score_higher():
    normal = [make_event(peer_id=f"p{i}", offset_ms=i * 140) for i in range(6)]
    irregular = (
        [make_event(peer_id=f"p{i}", offset_ms=d) for i, d in enumerate([0, 4, 9, 850, 861])]
        + [make_event(peer_id="p0", offset_ms=k) for k in (1, 2, 3)]
    )
    assert _score(irregular) > _score(normal)
    assert 0.0 <= _score(irregular) <= 1.0


def test_large_fanout_contributes():
    wide = [make_event(peer_id=f"peer-{i:03d}", offset_ms=i * 20) for i in range(40)]
    assert _score(wide) > 0.0
    assert _score(wide) <= 1.0


def test_deterministic():
    events = [make_event(peer_id=f"p{i}", offset_ms=i * 11) for i in range(7)]
    assert _score(events) == _score(list(reversed(events)))
