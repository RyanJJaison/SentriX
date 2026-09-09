"""
Integration seam for the Graph Analysis Engine, Traffic Correlation Engine,
and Fusion Engine (Technical Architecture §3.4-3.6), which other teammates
own. Until their modules are wired in, every method here returns
deterministic mock data — same address always yields the same score — so
the API and dashboard are fully demoable in isolation.

To integrate: replace the body of each method with a call into the real
Neo4j-backed graph store (see app.db.neo4j_client) and the fusion engine's
output, keeping the same signatures and return shapes.
"""
import hashlib
from datetime import datetime, timezone

from app.models.schemas import Alert, AddressRisk, GraphEdge, GraphNode, RiskFactors, SubgraphResponse

# In-memory cache of the last computed score per address, refreshed by the
# rescoring scheduler (Technical Architecture §3.7).
_score_cache: dict[str, AddressRisk] = {}


def _pseudo_random(seed: str, salt: str = "") -> float:
    digest = hashlib.sha256(f"{seed}{salt}".encode()).hexdigest()
    return int(digest[:8], 16) / 0xFFFFFFFF


def _compute_address_risk(address: str) -> AddressRisk:
    ppr = _pseudo_random(address, "ppr")
    gnn = _pseudo_random(address, "gnn")
    traffic = _pseudo_random(address, "traffic")
    weights = {"gnn": 0.6, "ppr": 0.15, "traffic": 0.25}
    fused = gnn * weights["gnn"] + ppr * weights["ppr"] + traffic * weights["traffic"]

    return AddressRisk(
        address=address,
        risk_score=round(fused, 4),
        contributing_factors=RiskFactors(
            gnn_score=round(gnn, 4),
            ppr_score=round(ppr, 4),
            traffic_anomaly_score=round(traffic, 4),
            weights=weights,
        ),
        last_updated=datetime.now(timezone.utc).isoformat(),
    )


def get_address_risk(address: str) -> AddressRisk:
    if address not in _score_cache:
        _score_cache[address] = _compute_address_risk(address)
    return _score_cache[address]


def list_alerts(threshold: float = 0.8, limit: int = 50) -> list[Alert]:
    # Mock "recently active" address pool. Replace with a query against
    # the graph store for addresses touched since the last rescoring cycle.
    candidate_addresses = [f"1MockAddr{i:04d}" for i in range(200)]

    alerts: list[Alert] = []
    for addr in candidate_addresses:
        risk = get_address_risk(addr)
        if risk.risk_score >= threshold:
            alerts.append(
                Alert(
                    id=hashlib.sha1(addr.encode()).hexdigest()[:10],
                    address=addr,
                    risk_score=risk.risk_score,
                    reason="Fused GNN + traffic-anomaly score above threshold",
                    flagged_at=risk.last_updated,
                )
            )
        if len(alerts) >= limit:
            break

    return sorted(alerts, key=lambda a: a.risk_score, reverse=True)


def get_subgraph(address: str, depth: int = 1) -> SubgraphResponse:
    neighbor_count = 3 + int(_pseudo_random(address, "neighbors") * 4)
    nodes = [GraphNode(id=address, label=address, risk_score=get_address_risk(address).risk_score)]
    edges: list[GraphEdge] = []

    for i in range(neighbor_count):
        neighbor = f"{address}-N{i}"
        nodes.append(
            GraphNode(id=neighbor, label=neighbor, risk_score=get_address_risk(neighbor).risk_score)
        )
        edges.append(
            GraphEdge(
                source=address,
                target=neighbor,
                tx_id=hashlib.sha1(f"{address}{neighbor}".encode()).hexdigest()[:16],
                amount=round(_pseudo_random(address, f"amount{i}") * 5, 6),
            )
        )

    return SubgraphResponse(center=address, depth=depth, nodes=nodes, edges=edges)


def rescore_neighborhood(changed_addresses: list[str]) -> int:
    """Incrementally recompute scores for a set of addresses (Technical
    Architecture §3.7: PPR + GNN inference on the local neighborhood only,
    not the full graph). Returns the number of addresses rescored."""
    for address in changed_addresses:
        _score_cache[address] = _compute_address_risk(address)
    return len(changed_addresses)
