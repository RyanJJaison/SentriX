"""
Wire-format checks for the passive Bitcoin P2P feed (`scripts/btc_p2p_feed.py`).

The feed only has to speak *just enough* of the protocol for real peers to keep
talking to it; these tests pin the framing so a broken header can't silently
turn into "no traffic captured".
"""
from __future__ import annotations

import socket
import struct
import threading
from hashlib import sha256

import pytest

btc = pytest.importorskip("scripts.btc_p2p_feed")


def test_message_header_is_spec_shaped():
    msg = btc._message("version", b"\x01\x02\x03")
    magic, cmd, length = struct.unpack("<I12sI", msg[:20])
    assert magic == btc.MAINNET_MAGIC
    assert cmd == b"version" + b"\x00" * 5  # null-padded to 12
    assert length == 3
    assert msg[20:24] == sha256(sha256(b"\x01\x02\x03").digest()).digest()[:4]
    assert msg[24:] == b"\x01\x02\x03"


def test_empty_payload_checksum():
    # verack / getaddr carry no payload; checksum is that of the empty string
    msg = btc._message("verack", b"")
    assert struct.unpack("<I", msg[16:20])[0] == 0
    assert msg[20:24] == sha256(sha256(b"").digest()).digest()[:4]
    assert len(msg) == 24


@pytest.mark.parametrize(
    "n, expected",
    [(0, b"\x00"), (0xFC, b"\xfc"), (0xFD, b"\xfd\xfd\x00"), (0x1234, b"\xfd\x34\x12")],
)
def test_varint(n, expected):
    assert btc._varint(n) == expected


def test_netaddr_is_16_byte_ipv4_mapped():
    out = btc._netaddr("8.8.8.8", 8333)
    assert len(out) == 26
    assert out[8:18] == b"\x00" * 10
    assert out[18:20] == b"\xff\xff"
    assert out[20:24] == socket.inet_aton("8.8.8.8")
    assert out[24:26] == struct.pack(">H", 8333)  # port is big-endian


def test_version_payload_decodes():
    p = btc._version_payload("1.2.3.4")
    ver, services, _ts = struct.unpack("<iQq", p[:20])
    assert ver == btc.PROTOCOL_VERSION
    assert services == 0
    assert p.endswith(b"\x01")  # relay flag on -> peers announce mempool txs
    assert btc.USER_AGENT in p


def test_read_message_round_trips_over_a_socket():
    a, b = socket.socketpair()
    try:
        payload = b"ping-nonce"
        a.sendall(btc._message("ping", payload))
        # a little trailing junk must not confuse the framing
        a.sendall(b"\x00\x00")
        command, got = btc._read_message(b)
        assert command == "ping"
        assert got == payload
    finally:
        a.close()
        b.close()


def test_read_message_rejects_bad_magic():
    a, b = socket.socketpair()
    try:
        a.sendall(struct.pack("<I", 0x11111111) + b"x" * 20)
        with pytest.raises(ConnectionError):
            btc._read_message(b)
    finally:
        a.close()
        b.close()


def test_discover_peers_handles_no_network(monkeypatch):
    def boom(*_a, **_k):
        raise socket.gaierror("no dns")

    monkeypatch.setattr(btc.socket, "getaddrinfo", boom)
    assert btc.discover_peers(8) == []


def test_peer_loop_never_raises(monkeypatch):
    """A peer that fails to connect must not propagate out of the thread."""
    monkeypatch.setattr(btc, "_session", lambda ip: (_ for _ in ()).throw(OSError("refused")))
    btc._stop.clear()
    t = threading.Thread(target=btc._peer_loop, args=("10.255.255.1",), daemon=True)
    t.start()
    btc._stop.set()  # let the backoff wait return immediately
    t.join(timeout=5)
    assert not t.is_alive()
