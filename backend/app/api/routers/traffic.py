"""
Traffic Correlation REST API (Technical Architecture §3.5 / §3.9).

Same JWT + role gate as the other data endpoints
(admin / investigator / analyst); every request is audit-logged by the
existing middleware in `app.main`.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status

from app.api.deps import require_role
from app.capture.manager import capture_manager
from app.capture.tshark_capture import tshark_available
from app.core.config import settings
from app.models.schemas import UserPublic
from app.models.traffic import CorrelationResult, PropagationSummary, TrafficStatus
from app.services import traffic_correlation

router = APIRouter(prefix="/traffic", tags=["traffic"])

_ROLES = require_role("admin", "investigator", "analyst")
_ID_PATTERN = r"^[A-Za-z0-9_.:-]{1,128}$"


@router.get("/status", response_model=TrafficStatus)
def traffic_status(user: UserPublic = Depends(_ROLES)) -> TrafficStatus:
    traffic_correlation.ensure_seeded()
    s = traffic_correlation.engine.stats()
    return TrafficStatus(
        mode=capture_manager.mode,
        capture_running=capture_manager.running,
        window_seconds=traffic_correlation.engine.window_seconds,
        event_count=s["event_count"],
        transaction_count=s["transaction_count"],
        peer_count=s["peer_count"],
        oldest_event=s["oldest_event"],
        newest_event=s["newest_event"],
        tshark_available=tshark_available(settings.tshark_path),
    )


@router.get("/anomalies", response_model=list[CorrelationResult])
def list_anomalies(
    min_score: float = Query(0.0, ge=0.0, le=1.0),
    limit: int = Query(50, ge=1, le=200),
    user: UserPublic = Depends(_ROLES),
) -> list[CorrelationResult]:
    traffic_correlation.ensure_seeded()
    return traffic_correlation.engine.detect_anomalies(min_score=min_score, limit=limit)


@router.get("/{entity_id}/correlation", response_model=CorrelationResult)
def transaction_correlation(
    entity_id: str = Path(..., pattern=_ID_PATTERN, description="transaction id or peer id"),
    user: UserPublic = Depends(_ROLES),
) -> CorrelationResult:
    traffic_correlation.ensure_seeded()
    result = traffic_correlation.engine.correlate_transaction(entity_id)
    if result is None:
        result = traffic_correlation.engine.score_peer(entity_id)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No traffic observations for {entity_id!r} in the current window",
        )
    return result


@router.get("/{txid}/propagation", response_model=PropagationSummary)
def transaction_propagation(
    txid: str = Path(..., pattern=_ID_PATTERN, description="transaction id"),
    user: UserPublic = Depends(_ROLES),
) -> PropagationSummary:
    traffic_correlation.ensure_seeded()
    result = traffic_correlation.engine.correlate_transaction(txid)
    if result is None or result.propagation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No propagation data for transaction {txid!r}",
        )
    return result.propagation
