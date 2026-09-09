"""
Traffic Correlation Engine (Technical Architecture §3.5).

    TrafficEvent stream ─> bounded in-memory window ─> per-transaction /
    per-peer correlation ─> four explainable heuristic features ─> weighted
    anomaly score + contributing factors ─> fusion / risk service.

Boundary rules: this module imports nothing from FastAPI, Neo4j or the JWT
layer. It consumes `TrafficEvent`, emits `CorrelationResult`. It does NOT own
the final risk score — the fusion layer decides how much the traffic signal
counts (see `risk_service._compute_address_risk`).

Heuristic traffic anomalies are SIGNALS, not proof of malicious activity.
"""
from __future__ import annotations

import hashlib
import logging
import math
import statistics
import threading
import time
from collections import Counter, deque
from collections.abc import Iterable
from datetime import datetime, timedelta, timezone

from app.core.config import settings
from app.models.traffic import (
    CorrelationResult,
    Factor,
    PropagationPeer,
    PropagationSummary,
    TrafficEvent,
)

logger = logging.getLogger("traffic.engine")

_FEATURE_KEYS = (
    "broadcast_timing",
    "burst_activity",
    "peer_concentration",
    "propagation_irregularity",
)


def _clip01(x: float) -> float:
    return 0.0 if x <= 0 else 1.0 if x >= 1 else float(x)


def _percentile(sorted_vals: list[float], pct: float) -> float:
    if not sorted_vals:
        return 0.0
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    k = (len(sorted_vals) - 1) * pct / 100.0
    lo, hi = math.floor(k), math.ceil(k)
    if lo == hi:
        return sorted_vals[int(k)]
    return sorted_vals[lo] * (hi - k) + sorted_vals[hi] * (k - lo)


# --------------------------------------------------------------------------- #
# Feature helpers (small, pure, independently testable)
# --------------------------------------------------------------------------- #


def first_seen_per_peer(events: list[TrafficEvent]) -> dict[str, datetime]:
    """Earliest observation timestamp for each peer."""
    out: dict[str, datetime] = {}
    for e in sorted(events, key=lambda ev: ev.timestamp):
        out.setdefault(e.peer_id, e.timestamp)
    return out


def build_propagation(txid: str, events: list[TrafficEvent]) -> PropagationSummary:
    per_peer = first_seen_per_peer(events)
    if not per_peer:
        return PropagationSummary(txid=txid)
    first = min(per_peer.values())
    last = max(per_peer.values())
    obs = Counter(e.peer_id for e in events)
    peers = [
        PropagationPeer(
            peer_id=pid,
            delay_ms=round((ts - first).total_seconds() * 1000.0, 3),
            observations=obs[pid],
        )
        for pid, ts in sorted(per_peer.items(), key=lambda kv: kv[1])
    ]
    delays = sorted(p.delay_ms for p in peers)
    return PropagationSummary(
        txid=txid,
        first_seen=first,
        last_seen=last,
        propagation_duration_ms=round((last - first).total_seconds() * 1000.0, 3),
        peer_count=len(per_peer),
        median_delay_ms=round(statistics.median(delays), 3),
        p95_delay_ms=round(_percentile(delays, 95), 3),
        peers=peers,
    )


def broadcast_timing_score(prop: PropagationSummary) -> float:
    """
    Compressed propagation across several peers -> anomaly. A long, lopsided
    tail contributes a little too. Normal, evenly-spaced propagation -> ~0.
    """
    if prop.peer_count < 1 or not prop.peers:
        return 0.0
    delays = [p.delay_ms for p in prop.peers]
    near = settings.traffic_near_simultaneous_ms
    sim_ratio = sum(1 for d in delays if d <= near) / len(delays)
    compression = sim_ratio * _clip01(prop.peer_count / 4.0)
    tail = _clip01((prop.p95_delay_ms - prop.median_delay_ms) / 1500.0)
    return _clip01(0.75 * compression + 0.25 * tail)


def burst_activity_score(
    tx_events: list[TrafficEvent],
    total_events_in_window: int,
    other_tx_counts: list[int],
    window_seconds: float,
) -> float:
    """
    Relative: this transaction's event volume vs. the median of the *other*
    transactions in the same window. Absolute: overall window rate vs. the
    configured baseline, scaled by this transaction's share. Score is the
    stronger of the two.
    """
    baseline_ratio = settings.traffic_burst_threshold_ratio
    n = len(tx_events)

    relative = 0.0
    if other_tx_counts:
        median_count = max(1.0, statistics.median(other_tx_counts))
        ratio = n / median_count
        relative = _clip01((ratio - 1.0) / max(1e-6, baseline_ratio - 1.0))

    absolute = 0.0
    if window_seconds > 0 and total_events_in_window > 0:
        window_rate = total_events_in_window / window_seconds
        rate_ratio = window_rate / max(1e-6, settings.traffic_burst_baseline_rate)
        share = n / total_events_in_window
        absolute = _clip01((rate_ratio - 1.0) / max(1e-6, baseline_ratio - 1.0)) * share

    return _clip01(max(relative, absolute))


def peer_concentration_score(tx_events: list[TrafficEvent]) -> float:
    """Low peer diversity / one dominant peer -> higher score. One feature only."""
    obs = Counter(e.peer_id for e in tx_events)
    n_peers = len(obs)
    if n_peers == 0:
        return 0.0
    if n_peers == 1:
        return 1.0
    total = sum(obs.values())
    probs = [c / total for c in obs.values()]
    entropy = -sum(p * math.log2(p) for p in probs)
    norm_entropy = entropy / math.log2(n_peers)
    dominant = max(obs.values()) / total
    return _clip01(0.45 * (1.0 - norm_entropy) + 0.55 * dominant)


def propagation_irregularity_score(
    tx_events: list[TrafficEvent],
    prop: PropagationSummary,
    timing: float,
    concentration: float,
) -> float:
    """Blend of duplicate observations, uneven timing gaps, fan-out and compression."""
    total = len(tx_events)
    n_peers = prop.peer_count
    repeats = (total - n_peers) / total if total else 0.0

    delays = sorted(p.delay_ms for p in prop.peers)
    deltas = [b - a for a, b in zip(delays, delays[1:])]
    gap_irr = 0.0
    if len(deltas) >= 2:
        mean_gap = statistics.fmean(deltas)
        if mean_gap > 0:
            cov = statistics.pstdev(deltas) / mean_gap
            gap_irr = _clip01(cov / 2.0)

    fanout_irr = _clip01(
        max(0, n_peers - settings.traffic_expected_fanout) / max(1, settings.traffic_expected_fanout)
    )

    return _clip01(
        0.30 * repeats
        + 0.30 * gap_irr
        + 0.20 * timing
        + 0.10 * fanout_irr
        + 0.10 * concentration
    )


_EXPLAIN = {
    "broadcast_timing": (
        "Transaction reached {pc} peers within {near:.0f} ms of each other, "
        "which is more compressed than a typical relay."
    ),
    "burst_activity": (
        "Event volume for this transaction was well above the median for the "
        "current {win}s window / the configured baseline."
    ),
    "peer_concentration": (
        "Observations were dominated by a small set of peers (low peer entropy)."
    ),
    "propagation_irregularity": (
        "Propagation showed uneven timing, repeated announcements or unusual fan-out."
    ),
}


def score_from_features(features: dict[str, float], *, peer_count: int) -> tuple[float, list[Factor]]:
    weights = {
        "broadcast_timing": settings.traffic_weight_broadcast_timing,
        "burst_activity": settings.traffic_weight_burst,
        "peer_concentration": settings.traffic_weight_peer_concentration,
        "propagation_irregularity": settings.traffic_weight_propagation_irregularity,
    }
    wsum = sum(weights.values()) or 1.0
    anomaly = sum(features[k] * weights[k] for k in _FEATURE_KEYS) / wsum

    factors = [
        Factor(
            name=k,
            score=round(features[k], 4),
            weight=round(weights[k] / wsum, 4),
            contribution=round(features[k] * weights[k] / wsum, 4),
            explanation=_EXPLAIN[k].format(
                pc=peer_count, near=settings.traffic_near_simultaneous_ms,
                win=settings.traffic_window_seconds,
            ),
        )
        for k in _FEATURE_KEYS
    ]
    factors.sort(key=lambda f: f.contribution, reverse=True)
    return _clip01(anomaly), factors


def confidence_from_evidence(event_count: int, peer_count: int) -> float:
    return round(
        _clip01(
            0.25
            + 0.50 * _clip01(event_count / 20.0)
            + 0.25 * _clip01(peer_count / 6.0)
        ),
        4,
    )


# --------------------------------------------------------------------------- #
# Engine
# --------------------------------------------------------------------------- #


class TrafficCorrelationEngine:
    """Bounded in-memory window of `TrafficEvent`s + correlation queries."""

    def __init__(self, window_seconds: int | None = None, max_events: int | None = None) -> None:
        self.window_seconds = window_seconds or settings.traffic_window_seconds
        self.max_events = max_events or settings.traffic_max_events
        self._events: deque[TrafficEvent] = deque()
        self._lock = threading.Lock()
        self._cache: list[CorrelationResult] = []
        self._cache_at = 0.0

    # -- ingestion / window management -- #

    def ingest(self, events: Iterable[TrafficEvent]) -> int:
        added = 0
        with self._lock:
            for e in events:
                self._events.append(e)
                added += 1
            self._evict_locked()
        if added:
            self._cache_at = 0.0
        return added

    def clear(self) -> None:
        with self._lock:
            self._events.clear()
            self._cache = []
            self._cache_at = 0.0

    def _reference_time(self) -> datetime:
        if not self._events:
            return datetime.now(timezone.utc)
        return max(self._events[0].timestamp, self._events[-1].timestamp)

    def _evict_locked(self) -> None:
        if not self._events:
            return
        cutoff = self._reference_time() - timedelta(seconds=self.window_seconds)
        while self._events and self._events[0].timestamp < cutoff:
            self._events.popleft()
        while len(self._events) > self.max_events:
            self._events.popleft()

    def _snapshot(self) -> list[TrafficEvent]:
        with self._lock:
            self._evict_locked()
            return list(self._events)

    # -- introspection -- #

    def stats(self) -> dict:
        snap = self._snapshot()
        txids = {e.txid for e in snap if e.txid}
        peers = {e.peer_id for e in snap}
        return {
            "event_count": len(snap),
            "transaction_count": len(txids),
            "peer_count": len(peers),
            "oldest_event": snap[0].timestamp if snap else None,
            "newest_event": snap[-1].timestamp if snap else None,
        }

    # -- correlation -- #

    def correlate_transaction(self, txid: str, snapshot: list[TrafficEvent] | None = None) -> CorrelationResult | None:
        snap = snapshot if snapshot is not None else self._snapshot()
        tx_events = [e for e in snap if e.txid == txid]
        if not tx_events:
            return None

        prop = build_propagation(txid, tx_events)
        counts = Counter(e.txid for e in snap if e.txid)
        other_counts = [c for t, c in counts.items() if t != txid]

        timing = broadcast_timing_score(prop)
        burst = burst_activity_score(tx_events, len(snap), other_counts, self.window_seconds)
        concentration = peer_concentration_score(tx_events)
        irregular = propagation_irregularity_score(tx_events, prop, timing, concentration)

        features = {
            "broadcast_timing": round(timing, 4),
            "burst_activity": round(burst, 4),
            "peer_concentration": round(concentration, 4),
            "propagation_irregularity": round(irregular, 4),
        }
        anomaly, factors = score_from_features(features, peer_count=prop.peer_count)

        return CorrelationResult(
            entity_id=txid,
            entity_type="transaction",
            anomaly_score=round(anomaly, 4),
            confidence=confidence_from_evidence(len(tx_events), prop.peer_count),
            event_count=len(tx_events),
            peer_count=prop.peer_count,
            first_seen=prop.first_seen,
            last_seen=prop.last_seen,
            features=features,
            factors=factors,
            propagation=prop,
        )

    def score_peer(self, peer_id: str, snapshot: list[TrafficEvent] | None = None) -> CorrelationResult | None:
        snap = snapshot if snapshot is not None else self._snapshot()
        peer_events = [e for e in snap if e.peer_id == peer_id]
        if not peer_events:
            return None

        txids = [t for t in {e.txid for e in peer_events} if t]
        per_tx = [r for t in txids if (r := self.correlate_transaction(t, snap)) is not None]

        def _mean(key: str) -> float:
            vals = [r.features[key] for r in per_tx]
            return statistics.fmean(vals) if vals else 0.0

        tx_counts = list(Counter(e.txid for e in snap if e.txid).values())
        peer_burst = burst_activity_score(peer_events, len(snap), tx_counts, self.window_seconds)
        peer_conc = peer_concentration_score(peer_events)

        features = {
            "broadcast_timing": round(_mean("broadcast_timing"), 4),
            "burst_activity": round(max(peer_burst, _mean("burst_activity")), 4),
            "peer_concentration": round(max(peer_conc, _mean("peer_concentration")), 4),
            "propagation_irregularity": round(_mean("propagation_irregularity"), 4),
        }
        anomaly, factors = score_from_features(features, peer_count=1)
        return CorrelationResult(
            entity_id=peer_id,
            entity_type="peer",
            anomaly_score=round(anomaly, 4),
            confidence=confidence_from_evidence(len(peer_events), len(txids) or 1),
            event_count=len(peer_events),
            peer_count=1,
            first_seen=min(e.timestamp for e in peer_events),
            last_seen=max(e.timestamp for e in peer_events),
            features=features,
            factors=factors,
        )

    def detect_anomalies(self, min_score: float = 0.0, limit: int = 50) -> list[CorrelationResult]:
        snap = self._snapshot()
        txids = sorted({e.txid for e in snap if e.txid})
        results = [
            r
            for t in txids
            if (r := self.correlate_transaction(t, snap)) is not None and r.anomaly_score >= min_score
        ]
        results.sort(key=lambda r: r.anomaly_score, reverse=True)
        return results[:limit]

    def current_anomalies(self, max_age_s: float = 10.0) -> list[CorrelationResult]:
        """Cached `detect_anomalies()` (kept warm by the scheduler)."""
        if self._cache and (time.monotonic() - self._cache_at) < max_age_s:
            return self._cache
        self._cache = self.detect_anomalies(limit=200)
        self._cache_at = time.monotonic()
        return self._cache

    def refresh(self) -> dict:
        """Recompute the anomaly snapshot. Never raises on an empty window."""
        try:
            results = self.detect_anomalies(limit=200)
        except Exception:  # noqa: BLE001 - defensive: rescoring must not break
            logger.exception("traffic detect_anomalies failed")
            results = []
        self._cache = results
        self._cache_at = time.monotonic()
        s = self.stats()
        return {
            "events": s["event_count"],
            "transactions": s["transaction_count"],
            "anomalies": len(results),
            "top_score": results[0].anomaly_score if results else 0.0,
        }


# --------------------------------------------------------------------------- #
# Module singleton + demo seeding + fusion adapter
# --------------------------------------------------------------------------- #

engine = TrafficCorrelationEngine()

_seeded = False
_seed_lock = threading.Lock()


def _demo_mode() -> bool:
    return not settings.traffic_capture_enabled and not settings.pcap_replay_path


def ensure_seeded() -> None:
    """
    In pure demo mode (no live capture, no PCAP), seed the window once from the
    built-in fixtures so `/traffic/*` and the fusion integration work with no
    setup and without the app lifespan having run (e.g. under pytest).
    """
    global _seeded
    if _seeded:
        return
    with _seed_lock:
        if _seeded:
            return
        if _demo_mode() and not engine._snapshot():
            from app.capture.demo_fixtures import build_demo_events

            engine.ingest(build_demo_events(datetime.now(timezone.utc)))
            logger.info("seeded traffic engine with demo fixtures")
        _seeded = True


def refresh() -> dict:
    """Called by the rescoring scheduler. Re-seeds demo data if the window drained."""
    if _demo_mode() and not engine._snapshot():
        global _seeded
        _seeded = False
    ensure_seeded()
    return engine.refresh()


def get_address_traffic_anomaly(address: str) -> float | None:
    """
    Fusion adapter (Technical Architecture §3.6). Returns a traffic-anomaly
    contribution in [0,1] for `address`, or None when there is no traffic data
    (the risk service then keeps its existing fallback).

    NOTE: Bitcoin P2P traffic carries txids and peer IPs, not addresses. The
    address->transaction association belongs to the graph/ingestion layer. Until
    that index exists, this deterministically maps each address to one
    correlated transaction's traffic profile so the demo is stable and testable.
    """
    ensure_seeded()
    results = engine.current_anomalies()
    if not results:
        return None
    idx = int(hashlib.sha256(f"{address}|traffic-assoc".encode()).hexdigest()[:8], 16) % len(results)
    return round(results[idx].anomaly_score, 4)


def get_address_traffic_intel(address: str) -> dict:
    """`{traffic_anomaly_score, traffic_features, traffic_factors}` for the fusion layer."""
    ensure_seeded()
    results = engine.current_anomalies()
    if not results:
        return {"traffic_anomaly_score": None, "traffic_features": {}, "traffic_factors": []}
    idx = int(hashlib.sha256(f"{address}|traffic-assoc".encode()).hexdigest()[:8], 16) % len(results)
    r = results[idx]
    return {
        "traffic_anomaly_score": r.anomaly_score,
        "traffic_features": r.features,
        "traffic_factors": [f.model_dump() for f in r.factors],
    }
