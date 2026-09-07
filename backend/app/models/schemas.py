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
