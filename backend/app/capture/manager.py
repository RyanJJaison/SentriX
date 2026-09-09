"""
Owns the capture backend lifecycle and feeds events into the correlation
engine on a background daemon thread — the FastAPI event loop is never
blocked, and a capture failure logs but never crashes the app.

Selection:
  TRAFFIC_CAPTURE_ENABLED=true + TSHARK_INTERFACE  -> TsharkCapture (live)
  PCAP_REPLAY_PATH set                             -> PcapReplay (file)
  otherwise                                        -> demo fixtures (via engine)
"""
from __future__ import annotations

import logging
import threading

from app.capture.base import TrafficCapture
from app.capture.pcap_replay import PcapReplay
from app.capture.tshark_capture import TsharkCapture, tshark_available
from app.core.config import settings
from app.services.traffic_correlation import engine, ensure_seeded

logger = logging.getLogger("traffic.manager")

_BATCH = 64


class CaptureManager:
    def __init__(self) -> None:
        self._capture: TrafficCapture | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def mode(self) -> str:
        if self._capture is not None:
            return self._capture.mode
        return "demo_fixtures" if not settings.pcap_replay_path else "pcap_replay"

    def _select(self) -> TrafficCapture | None:
        if settings.traffic_capture_enabled and settings.tshark_interface:
            if not tshark_available():
                logger.error(
                    "TRAFFIC_CAPTURE_ENABLED=true but tshark was not found at %r — "
                    "live capture disabled; using demo/replay instead.",
                    settings.tshark_path,
                )
            else:
                try:
                    return TsharkCapture()
                except ValueError as exc:
                    logger.error("tshark capture misconfigured: %s", exc)
        if settings.pcap_replay_path:
            return PcapReplay()
        return None  # pure demo mode: engine seeds itself

    def start(self) -> None:
        if self.running:
            return
        ensure_seeded()
        self._capture = self._select()
        if self._capture is None:
            logger.info("traffic capture: demo-fixture mode (no live capture, no PCAP)")
            return

        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name="traffic-capture", daemon=True
        )
        self._thread.start()
        logger.info("traffic capture started (%s)", self._capture.mode)

    def _run(self) -> None:
        assert self._capture is not None
        buf: list = []
        try:
            for event in self._capture.stream():
                if self._stop.is_set():
                    break
                buf.append(event)
                if len(buf) >= _BATCH:
                    engine.ingest(buf)
                    buf = []
        except Exception:  # noqa: BLE001 - a capture crash must not take down the app
            logger.exception("traffic capture thread failed; continuing without live events")
        finally:
            if buf:
                engine.ingest(buf)
            logger.info("traffic capture thread stopped (%s)", self.mode)

    def stop(self) -> None:
        self._stop.set()
        if self._capture is not None:
            try:
                self._capture.stop()
            except Exception:  # noqa: BLE001
                logger.debug("capture.stop() raised", exc_info=True)
        if self._thread is not None:
            self._thread.join(timeout=6)
        self._thread = None


capture_manager = CaptureManager()
