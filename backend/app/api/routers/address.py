from fastapi import APIRouter, Depends

from app.api.deps import require_role
from app.models.schemas import AddressRisk, UserPublic
from app.services import risk_service

router = APIRouter(prefix="/address", tags=["address"])


@router.get("/{address_id}/risk", response_model=AddressRisk)
def get_address_risk(
    address_id: str,
    user: UserPublic = Depends(require_role("admin", "investigator", "analyst")),
) -> AddressRisk:
    return risk_service.get_address_risk(address_id)
