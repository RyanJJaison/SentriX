"""
Domain models for the Traffic Correlation Engine (Technical Architecture §3.5).

`TrafficEvent` is the normalized unit every capture backend must emit — the
correlation engine never sees tshark/PCAP-specific shapes. `CorrelationResult`
is the explainable output handed to the fusion layer and the REST API.
"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, field_validator

# Accepts hex txids, "peer-01", "10.0.0.1:8333", demo ids like "tx-normal-001".
_ID_ALLOWED = set(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.:-"
)


def is_safe_id(value: str, *, max_len: int = 128) -> bool:
    """True if `value` is a short identifier with no shell/path metacharacters."""
    return bool(value) and len(value) <= max_len and set(value) <= _ID_ALLOWED


class TrafficEvent(BaseModel):
    """One normalized observation of Bitcoin P2P network activity."""

    timestamp: datetime
    peer_id: str
    src_ip: str | None = None
    dst_ip: str | None = None
    src_port: int | None = None
    dst_port: int | None = None
    event_type: str = "packet"
    txid: str | None = None
    size: int | None = None
    protocol: str = "bitcoin"
    message_type: str | None = None
    raw_metadata: dict = Field(default_factory=dict)

    @field_validator("peer_id")
    @classmethod
    def _validate_peer_id(cls, v: str) -> str:
        if not is_safe_id(v):
            raise ValueError("peer_id contains unsupported characters")
        return v

    @field_validator("txid")
    @classmethod
    def _validate_txid(cls, v: str | None) -> str | None:
        if v is not None and not is_safe_id(v):
            raise ValueError("txid contains unsupported characters")
        return v


class Factor(BaseModel):
    """One contributing feature in an explainable anomaly score."""

    name: str
    score: float
    weight: float
    contribution: float
    explanation: str


class PropagationPeer(BaseModel):
    peer_id: str
    delay_ms: float
    observations: int = 1


class PropagationSummary(BaseModel):
    txid: str
    first_seen: datetime | None = None
    last_seen: datetime | None = None
    propagation_duration_ms: float = 0.0
    peer_count: int = 0
    median_delay_ms: float = 0.0
    p95_delay_ms: float = 0.0
    peers: list[PropagationPeer] = Field(default_factory=list)


class CorrelationResult(BaseModel):
    """Explainable traffic-anomaly assessment for a transaction or a peer."""

    entity_id: str
    entity_type: str = "transaction"
    anomaly_score: float
    confidence: float
    event_count: int
    peer_count: int
    first_seen: datetime | None = None
    last_seen: datetime | None = None
    features: dict[str, float] = Field(default_factory=dict)
    factors: list[Factor] = Field(default_factory=list)
    propagation: PropagationSummary | None = None


class TrafficStatus(BaseModel):
    mode: str
    capture_running: bool
    window_seconds: int
    event_count: int
    transaction_count: int
    peer_count: int
    oldest_event: datetime | None = None
    newest_event: datetime | None = None
    tshark_available: bool
