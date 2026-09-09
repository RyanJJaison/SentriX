"""
DEMO / TEST DATA ONLY — deterministic synthetic traffic.

These are *not* real Bitcoin network observations. They are hand-built
`TrafficEvent` sequences that exercise each detector with a known outcome, so
the API, the fusion integration and the dashboard are demoable and testable
with no capture hardware. Every event is tagged
`raw_metadata={"source": "demo_fixture"}`.

Offsets are seconds before a caller-supplied `reference_time`, so the fixtures
always land inside the correlation window.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from app.models.traffic import TrafficEvent

# (offset_seconds_before_reference, peer_id, message_type, txid|None)
_Spec = tuple[float, str, str, str | None]


def _normal() -> list[_Spec]:
    txid = "tx-normal-001"
    base = 25.0
    delays = [0.0, 0.12, 0.26, 0.41, 0.6, 0.83]
    return [
        (base - d, f"peer-n{idx:02d}", "inv", txid)
        for idx, d in enumerate(delays)
    ]


def _burst() -> list[_Spec]:
    txid = "tx-burst-001"
    specs: list[_Spec] = []
    # The transaction itself: 5 peers, ordinary timing.
    for idx, d in enumerate([0.0, 0.05, 0.12, 0.2, 0.35]):
        specs.append((9.0 - d, f"peer-b{idx:02d}", "inv", txid))
    # ...arriving inside a flood: 180 announcements across 20 peers in ~2s.
    for i in range(180):
        peer = f"peer-b{i % 20:02d}"
        offset = 9.0 - (i * 2.0 / 180.0)
        specs.append((offset, peer, "inv", txid))
    return specs


def _concentration() -> list[_Spec]:
    txid = "tx-concentration-001"
    specs: list[_Spec] = []
    # 7 of 10 observations from one peer -> low peer entropy.
    for i in range(7):
        specs.append((18.0 - i * 0.1, "peer-conc-01", "inv", txid))
    for i in range(2):
        specs.append((17.0 - i * 0.1, "peer-conc-02", "inv", txid))
    specs.append((16.5, "peer-conc-03", "inv", txid))
    return specs


def _irregular() -> list[_Spec]:
    txid = "tx-irregular-001"
    # Two tight clusters separated by a large gap + a repeating peer.
    delays = [0.0, 0.004, 0.009, 0.85, 0.861]
    specs: list[_Spec] = [
        (14.0 - d, f"peer-irr{idx:02d}", "inv", txid) for idx, d in enumerate(delays)
    ]
    specs += [(14.0 - 0.001 * k, "peer-irr00", "inv", txid) for k in range(1, 4)]
    return specs


def _suspicious() -> list[_Spec]:
    txid = "tx-suspicious-001"
    specs: list[_Spec] = []
    # Compressed propagation, dominated by one peer, inside a small burst.
    for i in range(30):
        peer = "peer-sus-01" if i % 3 else f"peer-sus-{i % 4:02d}"
        specs.append((6.0 - i * 1.0 / 30.0, peer, "inv", txid))
    specs += [(6.0 - 0.002 * k, "peer-sus-01", "inv", txid) for k in range(1, 6)]
    return specs


def _background() -> list[_Spec]:
    # A little non-transaction chatter so the window has realistic context.
    return [
        (40.0 - i * 3.0, f"peer-n{i % 6:02d}", "ping", None) for i in range(8)
    ]


_ALL: list[_Spec] = (
    _normal()
    + _burst()
    + _concentration()
    + _irregular()
    + _suspicious()
    + _background()
)

#: Transaction ids present in the demo set (for status / docs).
DEMO_TXIDS = [
    "tx-normal-001",
    "tx-burst-001",
    "tx-concentration-001",
    "tx-irregular-001",
    "tx-suspicious-001",
]


def build_demo_events(reference_time: datetime) -> list[TrafficEvent]:
    """Materialize the demo specs as `TrafficEvent`s ending at `reference_time`."""
    events: list[TrafficEvent] = []
    for offset, peer_id, message_type, txid in _ALL:
        events.append(
            TrafficEvent(
                timestamp=reference_time - timedelta(seconds=offset),
                peer_id=peer_id,
                src_ip="203.0.113." + peer_id[-1] if peer_id[-1].isdigit() else "203.0.113.1",
                dst_ip="198.51.100.1",
                src_port=40000 + (hash(peer_id) % 20000),
                dst_port=8333,
                event_type="inv" if message_type == "inv" else "packet",
                txid=txid,
                size=61 if message_type == "inv" else 32,
                protocol="bitcoin",
                message_type=message_type,
                raw_metadata={"source": "demo_fixture"},
            )
        )
    events.sort(key=lambda e: e.timestamp)
    return events
