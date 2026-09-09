"""
Capture pipeline: PcapReplay (JSONL) + CaptureManager -> correlation engine.

The tshark subprocess path can't run without tshark installed, but everything
else — normalized-event replay, fallbacks, the daemon feeding the engine, and
correlation over replayed traffic — is exercised here with no external deps.
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

from app.capture.manager import CaptureManager
from app.capture.pcap_replay import PcapReplay
from app.capture.tshark_capture import tshark_available
from app.models.traffic import TrafficEvent
from app.services import traffic_correlation


def _write_replay(tmp_path, txid="tx-replay-burst"):
    """A tight 3-peer burst for `txid` + a little unrelated background, written
    as JSONL of normalized TrafficEvents at 'now' so it lands in the window."""
    now = datetime.now(timezone.utc)
    rows: list[TrafficEvent] = []
    for i in range(12):
        rows.append(
            TrafficEvent(
                timestamp=now - timedelta(milliseconds=200 - i * 15),
                peer_id=f"peer-r{i % 3:02d}",
                src_ip=f"203.0.113.{i % 3}",
                dst_ip="198.51.100.9",
                src_port=45000 + i,
                dst_port=8333,
                event_type="inv",
                txid=txid,
                size=61,
                protocol="bitcoin",
                message_type="inv",
                raw_metadata={"source": "replay_test"},
            )
        )
    for i in range(6):
        rows.append(
            TrafficEvent(
                timestamp=now - timedelta(seconds=1 + i),
                peer_id=f"peer-bg{i:02d}",
                src_ip=f"198.51.100.{i}",
                dst_ip="198.51.100.9",
                src_port=46000 + i,
                dst_port=8333,
                event_type="packet",
                txid=None,
                size=32,
                protocol="bitcoin",
                message_type="ping",
                raw_metadata={"source": "replay_test"},
            )
        )
    path = tmp_path / "replay.jsonl"
    path.write_text(
        "\n".join(e.model_dump_json() for e in rows) + "\n", encoding="utf-8"
    )
    return path, txid, len(rows)


def test_pcap_replay_json_roundtrips_events(tmp_path):
    path, txid, total = _write_replay(tmp_path)
    events = list(PcapReplay(str(path)).stream())

    assert len(events) == total
    assert all(isinstance(e, TrafficEvent) for e in events)
    assert any(e.txid == txid for e in events)


def test_pcap_replay_json_skips_bad_lines(tmp_path):
    path, _txid, total = _write_replay(tmp_path)
    with path.open("a", encoding="utf-8") as fh:
        fh.write("{ this is not json\n")
        fh.write('{"timestamp": "nope"}\n')  # right type, invalid content

    events = list(PcapReplay(str(path)).stream())
    assert len(events) == total  # the two junk lines are dropped, replay continues


def test_pcap_replay_missing_file_falls_back_to_demo(tmp_path):
    replay = PcapReplay(str(tmp_path / "does-not-exist.jsonl"))
    events = list(replay.stream())

    assert replay.mode == "demo_fixtures"
    assert len(events) > 0
    assert all(isinstance(e, TrafficEvent) for e in events)


def test_pcap_replay_unsupported_suffix_falls_back(tmp_path):
    weird = tmp_path / "capture.txt"
    weird.write_text("not a capture", encoding="utf-8")

    replay = PcapReplay(str(weird))
    events = list(replay.stream())
    assert replay.mode == "demo_fixtures"
    assert len(events) > 0


def test_replayed_traffic_feeds_the_correlation_engine(tmp_path):
    path, txid, _total = _write_replay(tmp_path)
    traffic_correlation.engine.clear()
    traffic_correlation.engine.ingest(PcapReplay(str(path)).stream())

    result = traffic_correlation.engine.correlate_transaction(txid)
    assert result is not None
    assert result.event_count == 12
    assert 0.0 <= result.anomaly_score <= 1.0
    assert {f.name for f in result.factors} == {
        "broadcast_timing",
        "burst_activity",
        "peer_concentration",
        "propagation_irregularity",
    }
    assert result.propagation.peer_count == 3


def test_capture_manager_drains_replay_file_into_engine(tmp_path, monkeypatch):
    path, txid, _total = _write_replay(tmp_path)
    monkeypatch.setattr(
        traffic_correlation.settings, "pcap_replay_path", str(path)
    )
    monkeypatch.setattr(
        traffic_correlation.settings, "traffic_capture_enabled", False
    )

    mgr = CaptureManager()
    mgr.start()
    try:
        assert mgr.mode == "pcap_replay"
        deadline = time.time() + 5
        while mgr.running and time.time() < deadline:
            time.sleep(0.05)

        result = traffic_correlation.engine.correlate_transaction(txid)
        assert result is not None
        assert result.event_count == 12
    finally:
        mgr.stop()

    assert not mgr.running


def test_tshark_guard_reports_missing_binary():
    assert tshark_available("definitely-not-a-real-tshark-binary") is False
