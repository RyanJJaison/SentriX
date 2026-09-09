"""
Live packet capture via `tshark` (subprocess, never `shell=True`).

Runs `tshark -i <iface> -f <filter> -T ek -l` and turns each newline-JSON
record into a `TrafficEvent`. One malformed line never stops the stream;
stderr is drained and logged; `stop()` terminates the child cleanly.
"""
from __future__ import annotations

import json
import logging
import shutil
import subprocess
import threading
from collections.abc import Iterator

from app.capture.base import TrafficCapture
from app.capture.normalizer import normalize_ek_record
from app.core.config import settings
from app.models.traffic import TrafficEvent, is_safe_id

logger = logging.getLogger("traffic.tshark")


class TsharkNotAvailable(RuntimeError):
    pass


def tshark_available(path: str | None = None) -> bool:
    return shutil.which(path or settings.tshark_path) is not None


def _validate_interface(iface: str) -> str:
    # Interface comes from config, not an API parameter, but still guard it so a
    # stray value can't become an extra CLI token.
    if not iface or not is_safe_id(iface, max_len=64):
        raise ValueError(f"invalid TSHARK_INTERFACE: {iface!r}")
    return iface


class TsharkCapture(TrafficCapture):
    mode = "tshark"

    def __init__(
        self,
        interface: str | None = None,
        capture_filter: str | None = None,
        tshark_path: str | None = None,
    ) -> None:
        self._path = tshark_path or settings.tshark_path
        self._interface = _validate_interface(interface or settings.tshark_interface)
        self._filter = capture_filter if capture_filter is not None else settings.tshark_capture_filter
        self._proc: subprocess.Popen[str] | None = None
        self._stop = threading.Event()

    def _command(self) -> list[str]:
        cmd = [self._path, "-i", self._interface, "-T", "ek", "-l", "-n"]
        if self._filter:
            cmd += ["-f", self._filter]
        return cmd

    def stream(self) -> Iterator[TrafficEvent]:
        if not tshark_available(self._path):
            raise TsharkNotAvailable(
                f"tshark not found at {self._path!r}. Install Wireshark/tshark or set "
                "TRAFFIC_CAPTURE_ENABLED=false to use PCAP/demo mode."
            )

        logger.info("starting tshark capture: %s", " ".join(self._command()))
        self._proc = subprocess.Popen(  # noqa: S603 - fixed argv, no shell
            self._command(),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        threading.Thread(target=self._drain_stderr, name="tshark-stderr", daemon=True).start()

        assert self._proc.stdout is not None
        try:
            for line in self._proc.stdout:
                if self._stop.is_set():
                    break
                line = line.strip()
                if not line or line.startswith('{"index"'):
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    logger.debug("skipping non-JSON tshark line")
                    continue
                try:
                    event = normalize_ek_record(record)
                except Exception:  # noqa: BLE001 - one bad packet must not kill the stream
                    logger.debug("skipping unnormalizable tshark record", exc_info=True)
                    continue
                if event is not None:
                    yield event
        finally:
            self._terminate()

    def _drain_stderr(self) -> None:
        if self._proc is None or self._proc.stderr is None:
            return
        for line in self._proc.stderr:
            line = line.strip()
            if line:
                logger.warning("tshark: %s", line)

    def _terminate(self) -> None:
        proc, self._proc = self._proc, None
        if proc is None or proc.poll() is not None:
            return
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            logger.warning("tshark did not exit; killing")
            proc.kill()

    def stop(self) -> None:
        self._stop.set()
        self._terminate()
