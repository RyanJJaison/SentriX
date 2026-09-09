"""
Capture abstraction. The correlation engine depends only on this interface,
never on tshark's or a PCAP library's output format.

    TsharkCapture ─┐
                   ├─> Iterator[TrafficEvent] ─> TrafficCorrelationEngine
    PcapReplay ────┘
"""
from __future__ import annotations

import abc
from collections.abc import Iterator

from app.models.traffic import TrafficEvent


class TrafficCapture(abc.ABC):
    """A source of normalized `TrafficEvent`s."""

    #: Human-readable mode label, e.g. "tshark", "pcap_replay", "demo_fixtures".
    mode: str = "unknown"

    @abc.abstractmethod
    def stream(self) -> Iterator[TrafficEvent]:
        """
        Yield `TrafficEvent`s until the source is exhausted (replay) or
        `stop()` is called (live). Must not raise on a single malformed
        packet — skip it and carry on.
        """
        raise NotImplementedError

    def stop(self) -> None:
        """Ask the source to stop; safe to call multiple times / when not running."""
