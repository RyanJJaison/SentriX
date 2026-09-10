from pydantic import BaseModel


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserPublic(BaseModel):
    username: str
    role: str
    agency: str


class RiskFactors(BaseModel):
    gnn_score: float
    ppr_score: float
    traffic_anomaly_score: float
    weights: dict[str, float]


class AddressRisk(BaseModel):
    address: str
    risk_score: float
    contributing_factors: RiskFactors
    last_updated: str


class RankedAddress(BaseModel):
    """One row of the dashboard's risk-ranked address table.

    Deliberately carries only fields with a real source. The table also shows
    cluster, 24h delta, volume and last-seen columns; nothing in the pipeline or
    the traffic engine supplies those, so they are not invented here -- the
    frontend renders them as "not available" rather than as plausible numbers.
    """

    address: str
    risk_score: float
    risk_tier: str
    last_updated: str


class Alert(BaseModel):
    id: str
    address: str
    risk_score: float
    reason: str
    flagged_at: str


class GraphNode(BaseModel):
    id: str
    label: str
    risk_score: float


class GraphEdge(BaseModel):
    source: str
    target: str
    tx_id: str
    amount: float


class SubgraphResponse(BaseModel):
    center: str
    depth: int
    nodes: list[GraphNode]
    edges: list[GraphEdge]


class AuditLogEntry(BaseModel):
    timestamp: str
    user: str
    method: str
    path: str
    status_code: int
