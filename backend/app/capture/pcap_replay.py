"""
Deterministic replay for demos and tests.

Priority:
  1. a `.pcap`/`.pcapng` file  -> replayed through `tshark -r ... -T ek`
  2. a `.json`/`.jsonl` file    -> lines of already-normalized `TrafficEvent`s
  3. no path                    -> built-in demo fixtures (see `demo_fixtures`)

Only (1) can carry real Bitcoin traffic, and only if tshark is installed and
the capture actually contains dissectable P2P messages. (2) and (3) are
explicitly demo data.
"""
from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path

from app.capture.base import TrafficCapture
from app.capture.normalizer import normalize_ek_record
from app.capture.tshark_capture import tshark_available
from app.core.config import settings
from app.models.traffic import TrafficEvent

logger = logging.getLogger("traffic.replay")


class PcapReplay(TrafficCapture):
    mode = "pcap_replay"

    def __init__(self, path: str | None = None, tshark_path: str | None = None) -> None:
        raw = path if path is not None else settings.pcap_replay_path
        self._path = Path(raw).expanduser() if raw else None
        self._tshark = tshark_path or settings.tshark_path
        if self._path is None:
            self.mode = "demo_fixtures"

    def stream(self) -> Iterator[TrafficEvent]:
        if self._path is None:
            yield from self._demo()
            return
        if not self._path.is_file():
            logger.warning("PCAP_REPLAY_PATH %s not found; falling back to demo fixtures", self._path)
            self.mode = "demo_fixtures"
            yield from self._demo()
            return

        suffix = self._path.suffix.lower()
        if suffix in {".json", ".jsonl", ".ndjson"}:
            yield from self._replay_json()
        elif suffix in {".pcap", ".pcapng", ".cap"}:
            yield from self._replay_pcap()
        else:
            logger.warning("unsupported replay file type %s; using demo fixtures", suffix)
            self.mode = "demo_fixtures"
            yield from self._demo()

    def _demo(self) -> Iterator[TrafficEvent]:
        from app.capture.demo_fixtures import build_demo_events

        yield from build_demo_events(datetime.now(timezone.utc))

    def _replay_json(self) -> Iterator[TrafficEvent]:
        assert self._path is not None
        with self._path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield TrafficEvent.model_validate_json(line)
                except Exception:  # noqa: BLE001 - skip a bad line, keep replaying
                    logger.debug("skipping invalid event line in %s", self._path, exc_info=True)

    def _replay_pcap(self) -> Iterator[TrafficEvent]:
        import subprocess

        if not tshark_available(self._tshark):
            logger.warning(
                "tshark unavailable; cannot parse %s. Falling back to demo fixtures.", self._path
            )
            self.mode = "demo_fixtures"
            yield from self._demo()
            return

        cmd = [self._tshark, "-r", str(self._path), "-T", "ek", "-n"]
        logger.info("replaying pcap: %s", " ".join(cmd))
        proc = subprocess.run(  # noqa: S603 - fixed argv, no shell
            cmd, capture_output=True, text=True, timeout=120, check=False
        )
        if proc.returncode != 0:
            logger.warning("tshark -r failed (%s): %s", proc.returncode, proc.stderr.strip())
            self.mode = "demo_fixtures"
            yield from self._demo()
            return

        produced = 0
        for line in proc.stdout.splitlines():
            line = line.strip()
            if not line or line.startswith('{"index"'):
                continue
            try:
                record = json.loads(line)
                event = normalize_ek_record(record)
            except Exception:  # noqa: BLE001
                continue
            if event is not None:
                produced += 1
                yield event

        if produced == 0:
            logger.warning(
                "%s contained no dissectable Bitcoin traffic; using demo fixtures instead",
                self._path,
            )
            self.mode = "demo_fixtures"
            yield from self._demo()
