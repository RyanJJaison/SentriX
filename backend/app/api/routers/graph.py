from fastapi import APIRouter, Depends, Query

from app.api.deps import require_role
from app.models.schemas import SubgraphResponse, UserPublic
from app.services import risk_service

router = APIRouter(prefix="/graph", tags=["graph"])


@router.get("/{address_id}", response_model=SubgraphResponse)
def get_subgraph(
    address_id: str,
    depth: int = Query(1, ge=1, le=3),
    user: UserPublic = Depends(require_role("admin", "investigator", "analyst")),
) -> SubgraphResponse:
    return risk_service.get_subgraph(address_id, depth=depth)
