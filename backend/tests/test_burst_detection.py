from app.services.traffic_correlation import burst_activity_score
from tests.conftest import make_event

WIN = 60.0


def test_baseline_volume_scores_low():
    tx = [make_event(peer_id=f"p{i}", offset_ms=i * 100) for i in range(4)]
    others = [make_event(peer_id=f"q{i}", txid="tx-other", offset_ms=i * 100) for i in range(4)]
    score = burst_activity_score(tx, len(tx) + len(others), [len(others)], WIN)
    assert score < 0.2


def test_high_volume_transaction_scores_high():
    tx = [make_event(peer_id=f"p{i % 10}", offset_ms=i) for i in range(200)]
    small_count = 5
    total = len(tx) + small_count
    score = burst_activity_score(tx, total, [small_count], WIN)
    assert score > 0.8


def test_score_bounded_and_deterministic():
    tx = [make_event(peer_id=f"p{i}", offset_ms=i * 3) for i in range(30)]
    counts = [30, 5, 5]
    s1 = burst_activity_score(tx, 40, counts, WIN)
    s2 = burst_activity_score(list(reversed(tx)), 40, counts, WIN)
    assert 0.0 <= s1 <= 1.0
    assert s1 == s2


def test_empty_inputs_do_not_crash():
    assert burst_activity_score([], 0, [], WIN) == 0.0
    assert burst_activity_score([], 10, [10], 0.0) == 0.0
