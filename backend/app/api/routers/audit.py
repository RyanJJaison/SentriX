from fastapi import APIRouter, Depends, Query

from app.api.deps import require_role
from app.models.schemas import AuditLogEntry, UserPublic
from app.services import audit_service

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("/logs", response_model=list[AuditLogEntry])
def get_audit_logs(
    limit: int = Query(50, ge=1, le=1000),
    user: UserPublic = Depends(require_role("admin")),
) -> list[AuditLogEntry]:
    return [
        AuditLogEntry(**entry)
        for entry in audit_service.read_recent(limit=limit)
        if "status_code" in entry
    ]
