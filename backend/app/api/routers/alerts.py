from fastapi import APIRouter, Depends, Query

from app.api.deps import require_role
from app.models.schemas import Alert, UserPublic
from app.services import risk_service

router = APIRouter(prefix="/alerts", tags=["alerts"])


@router.get("", response_model=list[Alert])
def list_alerts(
    threshold: float = Query(0.8, ge=0.0, le=1.0),
    limit: int = Query(50, ge=1, le=500),
    user: UserPublic = Depends(require_role("admin", "investigator", "analyst")),
) -> list[Alert]:
    return risk_service.list_alerts(threshold=threshold, limit=limit)
