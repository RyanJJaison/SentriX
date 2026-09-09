from app.capture.demo_fixtures import DEMO_TXIDS
from app.capture.pcap_replay import PcapReplay
from tests.conftest import make_event


def test_no_path_yields_demo_fixtures():
    replay = PcapReplay(path=None)
    events = list(replay.stream())
    assert replay.mode == "demo_fixtures"
    assert len(events) > 50
    seen_txids = {e.txid for e in events if e.txid}
    for txid in DEMO_TXIDS:
        assert txid in seen_txids
    assert all(e.raw_metadata.get("source") == "demo_fixture" for e in events)


def test_demo_replay_is_deterministic_in_count():
    a = list(PcapReplay(path=None).stream())
    b = list(PcapReplay(path=None).stream())
    assert len(a) == len(b)


def test_missing_path_falls_back_to_demo(tmp_path):
    replay = PcapReplay(path=str(tmp_path / "nope.pcap"))
    events = list(replay.stream())
    assert replay.mode == "demo_fixtures"
    assert events


def test_jsonl_replay(tmp_path):
    f = tmp_path / "events.jsonl"
    lines = [
        make_event(peer_id="peer-A", txid="tx-json-1").model_dump_json(),
        "this is not json",
        make_event(peer_id="peer-B", txid="tx-json-2").model_dump_json(),
    ]
    f.write_text("\n".join(lines), encoding="utf-8")

    events = list(PcapReplay(path=str(f)).stream())
    assert [e.peer_id for e in events] == ["peer-A", "peer-B"]
    assert {e.txid for e in events} == {"tx-json-1", "tx-json-2"}
