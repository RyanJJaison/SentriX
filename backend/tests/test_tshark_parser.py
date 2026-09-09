from app.capture import normalizer
from app.capture.normalizer import flatten_layers, normalize_ek_record, normalize_fields

DOTTED = {
    "frame.time.epoch": "1767268800.5",
    "ip.src": "203.0.113.7",
    "ip.dst": "198.51.100.1",
    "tcp.srcport": "44321",
    "tcp.dstport": "8333",
    "frame.len": "125",
    "bitcoin.command": "inv",
    "bitcoin.inv.type": "1",
    "bitcoin.inv.hash": "AABBCCDD",
}


def test_normalize_dotted_fields():
    ev = normalize_fields(DOTTED)
    assert ev is not None
    assert ev.peer_id == "203.0.113.7:44321"  # non-8333 side
    assert ev.message_type == "inv"
    assert ev.txid == "AABBCCDD"
    assert ev.size == 125
    assert ev.protocol == "bitcoin"


def test_normalize_ek_underscored_fields():
    ek = {
        "frame_frame_time_epoch": ["1767268800.0"],
        "ip_ip_src": ["10.0.0.9"],
        "ip_ip_dst": ["10.0.0.1"],
        "tcp_tcp_srcport": ["8333"],
        "tcp_tcp_dstport": ["55000"],
        "bitcoin_bitcoin_command": ["tx"],
    }
    ev = normalize_fields(ek)
    assert ev is not None
    assert ev.peer_id == "10.0.0.1:55000"  # peer is the non-8333 side
    assert ev.message_type == "tx"
    assert ev.event_type == "tx_seen"


def test_non_inv_command_has_no_txid():
    fields = dict(DOTTED, **{"bitcoin.command": "getdata"})
    fields.pop("bitcoin.inv.type", None)
    ev = normalize_fields(fields)
    assert ev is not None and ev.txid is None


def test_missing_timestamp_returns_none():
    assert normalize_fields({"ip.src": "1.2.3.4"}) is None


def test_missing_ip_still_normalizes():
    ev = normalize_fields({"frame.time.epoch": "1767268800.0", "bitcoin.command": "ping"})
    assert ev is not None
    assert ev.peer_id == "unknown"
    assert ev.src_ip is None


def test_large_timestamp_and_bad_types_do_not_crash():
    ev = normalize_fields(
        {"frame.time.epoch": "32503680000.0", "frame.len": "not-a-number", "tcp.srcport": None}
    )
    assert ev is not None
    assert ev.size is None
    assert ev.timestamp.year >= 3000


def test_flatten_layers_nested_and_ek():
    flat = flatten_layers({"ip": {"ip": {"src": "1.1.1.1"}}, "tcp_tcp_srcport": "1234"})
    assert flat["ip.ip.src"] == "1.1.1.1"
    assert flat["tcp.tcp.srcport"] == "1234"


def test_normalize_ek_record_and_garbage():
    rec = {"timestamp": "1767268800500", "layers": {"frame_frame_time_epoch": ["1767268800.5"],
           "bitcoin_bitcoin_command": ["inv"], "ip_ip_src": ["8.8.8.8"], "tcp_tcp_dstport": ["8333"],
           "tcp_tcp_srcport": ["40000"]}}
    ev = normalize_ek_record(rec)
    assert ev is not None and ev.message_type == "inv"
    assert normalize_ek_record({"no": "layers"}) is None
    assert normalize_ek_record({"layers": "not-a-dict"}) is None


# --- real tshark 4.6 `-T ek` shape: per-layer sub-dicts, the layer name doubled
#     into every field, `frame.time*` as ISO8601 nanoseconds -----------------

def _real_ek_inv(local_ip="192.168.1.101", peer_ip="188.214.129.52"):
    return {
        "timestamp": "1788975156192",
        "layers": {
            "frame": {
                "frame_frame_time_epoch": "2026-09-09T17:32:36.192808500Z",
                "frame_frame_time": "2026-09-09T17:32:36.192808500Z",
                "frame_frame_len": "439",
            },
            "ip": {"ip_ip_src": peer_ip, "ip_ip_dst": local_ip, "ip_ip_addr": [peer_ip, local_ip]},
            "tcp": {"tcp_tcp_srcport": "8333", "tcp_tcp_dstport": "59891", "tcp_tcp_len": "385"},
            "bitcoin": {
                "bitcoin_bitcoin_command": "inv",
                "bitcoin_bitcoin_inv_count": "2",
                "bitcoin_bitcoin_inv_type": ["1", "1"],
                "bitcoin_bitcoin_inv_hash": [
                    "56:43:9a:f2:93:5b:e7:97:20:cd:cf:6c:0c:c6:d9:19",
                    "5d:e8:05:28:de:94:dd:f3:47:4a:37:3d:a1:04:11:3f",
                ],
            },
        },
    }


def test_real_ek46_inv_is_fully_parsed():
    ev = normalize_ek_record(_real_ek_inv())
    assert ev is not None
    assert ev.message_type == "inv"
    assert ev.event_type == "inv"
    assert ev.protocol == "bitcoin"
    assert ev.size == 439
    assert ev.src_ip == "188.214.129.52" and ev.dst_ip == "192.168.1.101"
    assert ev.src_port == 8333 and ev.dst_port == 59891
    assert ev.txid == "56439af2935be79720cdcf6c0cc6d919"  # first inv vector, colons stripped


def test_real_ek46_peer_is_the_remote_node(monkeypatch):
    # pretend this host owns 192.168.1.101 -> the peer must be the other end
    monkeypatch.setattr(normalizer, "_LOCAL_IPS", {"127.0.0.1", "192.168.1.101"})
    ev = normalize_ek_record(_real_ek_inv())
    assert ev.peer_id == "188.214.129.52:8333"


def test_flatten_dealiases_doubled_layer_prefix():
    flat = flatten_layers(_real_ek_inv()["layers"])
    assert flat["bitcoin.command"] == "inv"
    assert flat["ip.src"] == "188.214.129.52"
    assert flat["tcp.srcport"] == "8333"
    assert flat["frame.len"] == "439"


def test_iso_nanosecond_timestamp_survives():
    # drop the epoch-ms shortcut so the ISO frame.time path is exercised
    rec = _real_ek_inv()
    rec.pop("timestamp")
    ev = normalize_ek_record(rec)
    assert ev is not None
    assert ev.timestamp.year == 2026 and ev.timestamp.microsecond == 192808
