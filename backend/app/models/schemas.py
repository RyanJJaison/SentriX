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


class OverviewStats(BaseModel):
    """Counters behind the dashboard's summary cards.

    No trend or delta fields: nothing persists a previous cycle's values, so a
    percentage change would have to be invented. The cards render the current
    figure only.

    There is deliberately no "transactions analysed" counter. In the Elliptic
    dataset one node *is* one transaction, so it would be a duplicate of
    `addresses_monitored` under a grander label.
    """

    addresses_monitored: int
    high_risk_count: int
    # How many addresses were fused to produce `high_risk_count`. The count is
    # over the candidate pool, not the whole dataset, and the UI says so.
    high_risk_scanned: int
    critical_threshold: float
    # Held-out test metrics for the shipped checkpoint, not runtime confidence.
    model_test_auc: float
    model_test_f1: float


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
    """One edge of a transaction subgraph.

    No `amount`: Elliptic's public release is anonymised at the value level and
    ships no BTC transaction amounts, so there is no real figure to report. The
    field was removed rather than kept as a fabricated or always-null value.
    """

    source: str
    target: str
    tx_id: str


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
