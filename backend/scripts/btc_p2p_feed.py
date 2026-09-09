"""
Bitcoin P2P traffic feed — a minimal, read-only mainnet listener.

Purpose: give the Traffic Correlation Engine's live `tshark` capture something
real to see. `tshark -f "tcp port 8333"` only yields packets if this machine is
actually speaking the Bitcoin wire protocol; running this alongside the backend
produces a steady stream of genuine `inv` / `tx` / `addr` / `ping` messages from
real mainnet peers.

What it does:
  * resolves a few well-known DNS seeds to peer IPs
  * opens N concurrent TCP connections to port 8333
  * performs the real version / verack handshake (relay=1 so peers announce
    mempool transactions), answers `ping` with `pong`, sends periodic `getaddr`
  * reconnects with exponential backoff; one dead peer never stops the others

What it is NOT: no blocks are validated, no chain is stored, nothing is ever
sent that could relay a transaction. It is a passive observer that keeps just
enough of a conversation alive to receive announcements.

Usage:
    python -m scripts.btc_p2p_feed            # 8 peers, run until Ctrl-C
    python -m scripts.btc_p2p_feed --peers 12 --duration 300
"""
from __future__ import annotations

import argparse
import logging
import random
import signal
import socket
import struct
import sys
import threading
import time
from collections import Counter
from datetime import datetime, timezone

MAINNET_MAGIC = 0xD9B4BEF9  # little-endian on the wire
PROTOCOL_VERSION = 70016
BITCOIN_PORT = 8333
USER_AGENT = b"/sentrix-traffic-tap:0.1/"

DNS_SEEDS = (
    "seed.bitcoin.sipa.be",
    "dnsseed.bluematt.me",
    "seed.bitcoinstats.com",
    "seed.bitcoin.jonasschnelli.ch",
    "seed.btc.petertodd.net",
    "seed.bitcoin.wiz.biz",
    "dnsseed.emzy.de",
)

log = logging.getLogger("btc_p2p_feed")

_counts = Counter()
_counts_lock = threading.Lock()
_stop = threading.Event()


# --------------------------------------------------------------------------- #
# Wire protocol (only what a passive listener needs)
# --------------------------------------------------------------------------- #
def _checksum(payload: bytes) -> bytes:
    from hashlib import sha256

    return sha256(sha256(payload).digest()).digest()[:4]


def _message(command: str, payload: bytes) -> bytes:
    cmd = command.encode("ascii")
    if len(cmd) > 12:
        raise ValueError(command)
    return (
        struct.pack("<I", MAINNET_MAGIC)
        + cmd
        + b"\x00" * (12 - len(cmd))
        + struct.pack("<I", len(payload))
        + _checksum(payload)
        + payload
    )


def _netaddr(ip: str, port: int, *, services: int = 0) -> bytes:
    try:
        raw = socket.inet_aton(ip)
    except OSError:
        raw = b"\x00" * 4
    return struct.pack("<Q", services) + b"\x00" * 10 + b"\xff\xff" + raw + struct.pack(">H", port)


def _varstr(data: bytes) -> bytes:
    return _varint(len(data)) + data


def _varint(n: int) -> bytes:
    if n < 0xFD:
        return struct.pack("<B", n)
    if n <= 0xFFFF:
        return b"\xfd" + struct.pack("<H", n)
    if n <= 0xFFFFFFFF:
        return b"\xfe" + struct.pack("<I", n)
    return b"\xff" + struct.pack("<Q", n)


def _version_payload(peer_ip: str) -> bytes:
    now = int(time.time())
    nonce = random.getrandbits(64)
    return (
        struct.pack("<i", PROTOCOL_VERSION)
        + struct.pack("<Q", 0)  # our services: none
        + struct.pack("<q", now)
        + _netaddr(peer_ip, BITCOIN_PORT)  # addr_recv
        + _netaddr("0.0.0.0", 0)  # addr_from
        + struct.pack("<Q", nonce)
        + _varstr(USER_AGENT)
        + struct.pack("<i", 0)  # start_height
        + struct.pack("<?", True)  # relay -> peers send us mempool inv
    )


def _read_exact(sock: socket.socket, n: int) -> bytes:
    buf = bytearray()
    while len(buf) < n:
        if _stop.is_set():
            raise ConnectionAbortedError("stopping")
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("peer closed")
        buf += chunk
    return bytes(buf)


def _read_message(sock: socket.socket) -> tuple[str, bytes]:
    header = _read_exact(sock, 24)
    magic, cmd_raw, length = struct.unpack("<I12sI", header[:20])
    if magic != MAINNET_MAGIC:
        raise ConnectionError(f"bad magic {magic:#x}")
    if length > 4_000_000:
        raise ConnectionError(f"oversized message ({length})")
    payload = _read_exact(sock, length) if length else b""
    command = cmd_raw.split(b"\x00", 1)[0].decode("ascii", "replace")
    return command, payload


# --------------------------------------------------------------------------- #
# Per-peer session
# --------------------------------------------------------------------------- #
def _bump(command: str) -> None:
    with _counts_lock:
        _counts[command] += 1
        _counts["_total"] += 1


def _session(peer_ip: str) -> None:
    sock = socket.create_connection((peer_ip, BITCOIN_PORT), timeout=10)
    sock.settimeout(90)
    try:
        sock.sendall(_message("version", _version_payload(peer_ip)))
        got_verack = sent_verack = False
        last_getaddr = 0.0

        while not _stop.is_set():
            command, payload = _read_message(sock)
            _bump(command)

            if command == "version":
                sock.sendall(_message("verack", b""))
                sent_verack = True
            elif command == "verack":
                got_verack = True
            elif command == "ping":
                sock.sendall(_message("pong", payload[:8]))
            elif command == "sendcmpct" or command == "feefilter":
                pass  # informational, ignore

            if got_verack and sent_verack and time.time() - last_getaddr > 120:
                sock.sendall(_message("getaddr", b""))
                last_getaddr = time.time()
    finally:
        try:
            sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        sock.close()


def _peer_loop(peer_ip: str) -> None:
    backoff = 2.0
    while not _stop.is_set():
        started = time.time()
        try:
            log.info("connecting %s", peer_ip)
            _session(peer_ip)
        except Exception as exc:  # noqa: BLE001 - a peer dying must never escape
            log.debug("peer %s ended: %s", peer_ip, exc)
        if _stop.is_set():
            return
        # a session that lived a while resets the backoff
        backoff = 2.0 if time.time() - started > 30 else min(backoff * 1.8, 60.0)
        _stop.wait(backoff + random.random())


# --------------------------------------------------------------------------- #
# Peer discovery
# --------------------------------------------------------------------------- #
def discover_peers(want: int) -> list[str]:
    found: set[str] = set()
    for seed in random.sample(DNS_SEEDS, k=len(DNS_SEEDS)):
        if len(found) >= want * 3:
            break
        try:
            for info in socket.getaddrinfo(seed, BITCOIN_PORT, socket.AF_INET, socket.SOCK_STREAM):
                found.add(info[4][0])
        except socket.gaierror as exc:
            log.debug("seed %s failed: %s", seed, exc)
    peers = list(found)
    random.shuffle(peers)
    return peers[:want] if peers else []


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #
def _report_loop(interval: float) -> None:
    while not _stop.wait(interval):
        with _counts_lock:
            total = _counts["_total"]
            top = ", ".join(
                f"{cmd}={n}" for cmd, n in _counts.most_common(6) if cmd != "_total"
            )
        log.info("[%s] %d msgs seen  (%s)", datetime.now(timezone.utc).strftime("%H:%M:%S"), total, top)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Passive Bitcoin P2P listener for live traffic capture.")
    parser.add_argument("--peers", type=int, default=8, help="concurrent peer connections (default 8)")
    parser.add_argument("--duration", type=int, default=0, help="seconds to run, 0 = until Ctrl-C")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    def _sig(*_a: object) -> None:
        log.info("stopping...")
        _stop.set()

    signal.signal(signal.SIGINT, _sig)
    signal.signal(signal.SIGTERM, _sig)

    log.info("discovering peers via %d DNS seeds...", len(DNS_SEEDS))
    peers = discover_peers(args.peers)
    if not peers:
        log.error("no peers discovered (no network / DNS?). nothing to capture.")
        return 1
    log.info("connecting to %d peers: %s", len(peers), ", ".join(peers))

    threads = [threading.Thread(target=_peer_loop, args=(ip,), name=f"peer-{ip}", daemon=True) for ip in peers]
    threads.append(threading.Thread(target=_report_loop, args=(15.0,), name="report", daemon=True))
    for t in threads:
        t.start()

    deadline = time.time() + args.duration if args.duration else None
    try:
        while not _stop.is_set():
            if deadline and time.time() >= deadline:
                _stop.set()
                break
            time.sleep(0.5)
    except KeyboardInterrupt:
        _stop.set()

    with _counts_lock:
        total = _counts["_total"]
    log.info("done. %d messages observed across the session.", total)
    return 0


if __name__ == "__main__":
    sys.exit(main())
