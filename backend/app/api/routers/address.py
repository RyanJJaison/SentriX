from fastapi import APIRouter, Depends, Query

from app.api.deps import require_role
from app.models.schemas import AddressRisk, RankedAddress, UserPublic
from app.services import risk_service

router = APIRouter(prefix="/address", tags=["address"])

_ROLES = require_role("admin", "investigator", "analyst")


# Registered before /{address_id}/risk so the literal path is matched first and
# "ranked" is never captured as an address id.
@router.get("/ranked", response_model=list[RankedAddress])
def list_ranked_addresses(
    threshold: float = Query(0.0, ge=0.0, le=1.0),
    limit: int = Query(25, ge=1, le=500),
    user: UserPublic = Depends(_ROLES),
) -> list[RankedAddress]:
    """Risk-ranked addresses for the dashboard table.

    Shares its candidate pool, fused scores and ordering with /alerts, so the
    two dashboard panels cannot disagree about which addresses rank highest.
    """
    return risk_service.list_ranked_addresses(threshold=threshold, limit=limit)


@router.get("/{address_id}/risk", response_model=AddressRisk)
def get_address_risk(
    address_id: str,
    user: UserPublic = Depends(_ROLES),
) -> AddressRisk:
    return risk_service.get_address_risk(address_id)
