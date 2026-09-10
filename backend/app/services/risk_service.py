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
import json
import logging
import os
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

from app.models.schemas import Alert, AddressRisk, GraphEdge, GraphNode, RankedAddress, RiskFactors, SubgraphResponse
from app.services import traffic_correlation

log = logging.getLogger(__name__)

# In-memory cache of the last computed score per address, refreshed by the
# rescoring scheduler (Technical Architecture §3.7).
_score_cache: dict[str, AddressRisk] = {}

# Graph Analysis Engine output (src.export), keyed by Elliptic txId as a string.
# Overridable so tests and deployments can point at a different file.
_DEFAULT_SCORES_PATH = Path(__file__).resolve().parents[3] / "output" / "scores.jsonl"


def _pseudo_random(seed: str, salt: str = "") -> float:
    digest = hashlib.sha256(f"{seed}{salt}".encode()).hexdigest()
    return int(digest[:8], 16) / 0xFFFFFFFF


def _scores_path() -> Path:
    override = os.environ.get("SENTRIX_SCORES_PATH")
    return Path(override) if override else _DEFAULT_SCORES_PATH


@lru_cache(maxsize=1)
def _load_graph_scores() -> dict[str, tuple[float, float]]:
    """Load `output/scores.jsonl` into {address_id: (gnn_score, ppr_score)}.

    Cached for the process lifetime: the file is ~87 MB over ~204k records, so
    it is parsed once and only the two fields needed are retained rather than
    the whole record.

    The export's `graph_context` shape changed over time -- it used to carry a
    single `ppr_score` and now carries `ppr_fwd_score` alongside the reverse
    direction -- so both are accepted, preferring the explicit forward field.
    A missing file is not an error here: the caller falls back to mock scores
    per address, which is what keeps the API demoable without the pipeline.
    """
    path = _scores_path()
    if not path.is_file():
        log.warning(
            "Graph scores not found at %s; every address will use mock scores. "
            "Run `python -m src.export` to generate real scores.",
            path,
        )
        return {}

    scores: dict[str, tuple[float, float]] = {}
    skipped = 0
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
                context = record.get("graph_context") or {}
                ppr = context.get("ppr_fwd_score", context.get("ppr_score"))
                if ppr is None:
                    skipped += 1
                    continue
                scores[str(record["address_id"])] = (
                    float(record["risk_score"]),
                    float(ppr),
                )
            except (json.JSONDecodeError, KeyError, TypeError, ValueError):
                skipped += 1

    log.info(
        "Loaded %d graph scores from %s%s",
        len(scores),
        path,
        f" ({skipped} records skipped)" if skipped else "",
    )
    return scores


def _compute_address_risk(address: str) -> AddressRisk:
    # GRAPH ANALYSIS INTEGRATION POINT (Technical Architecture §3.4): the GNN
    # probability and PPR proximity score now come from the exported pipeline
    # output. Addresses absent from it -- demo addresses such as
    # "1MockAddr0001", which are not real Elliptic txIds -- keep the
    # deterministic mock so the dashboard stays demoable.
    real = _load_graph_scores().get(address)
    if real is not None:
        gnn, ppr = real
        log.debug("address %s: gnn=%.6f ppr=%.6f source=real", address, gnn, ppr)
    else:
        ppr = _pseudo_random(address, "ppr")
        gnn = _pseudo_random(address, "gnn")
        log.debug("address %s: gnn=%.6f ppr=%.6f source=fallback", address, gnn, ppr)
    # FUSION INTEGRATION POINT (Technical Architecture §3.6): the traffic
    # component now comes from the Traffic Correlation Engine's live anomaly
    # snapshot; if it has no data yet, fall back to the deterministic mock so
    # existing behaviour/tests are unchanged.
    traffic_signal = traffic_correlation.get_address_traffic_anomaly(address)
    traffic = traffic_signal if traffic_signal is not None else _pseudo_random(address, "traffic")
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


# How many of the highest-scoring graph addresses to re-fuse per alerts query.
# Fusing is cheap but not free (it adds the live traffic component per address),
# and an alert feed only ever displays the top slice, so the candidate pool is
# capped rather than fusing all ~204k exported addresses on every request.
_ALERT_CANDIDATE_POOL = 500


def _candidate_addresses() -> list[str]:
    """Bounded pool of the addresses most worth fusing, highest graph score first.

    Candidates come from `output/scores.jsonl` (via `_load_graph_scores`, the
    same loader `_compute_address_risk` uses), pre-ranked by the exported GNN
    score. Only a capped pool is returned: fusing is cheap but not free (it adds
    the live traffic component per address), and every consumer displays a top
    slice rather than all ~204k exported addresses.

    Ranking here is by the *exported* GNN score, which only decides which
    addresses are worth fusing; callers filter and re-sort on the fused score.
    The GNN term carries the largest weight (0.6), so the ordering is a good
    proxy for picking the pool.

    Falls back to the previous synthetic pool when no export is present, which
    keeps the API (and the dashboard) working without the pipeline.
    """
    graph_scores = _load_graph_scores()
    if not graph_scores:
        # No pipeline output on disk -- keep the demo pool so callers still
        # return something rather than an empty list.
        return [f"1MockAddr{i:04d}" for i in range(200)]
    return [
        address
        for address, _ in sorted(
            graph_scores.items(), key=lambda item: item[1][0], reverse=True
        )[:_ALERT_CANDIDATE_POOL]
    ]


def _ranked_risks(threshold: float, limit: int) -> list[AddressRisk]:
    """Fused risk for the candidate pool, filtered by `threshold`, best first.

    Shared by `list_alerts` and `list_ranked_addresses` so the ranking exists in
    one place. Each candidate is scored through `get_address_risk`, so the
    `risk_score` here is the same fused value `/address/{id}/risk` reports for
    that address rather than the raw graph score.

    Sorting happens before truncation deliberately: truncating first would
    return the top N of the first N matches rather than the N highest-scoring
    addresses overall.
    """
    risks = [
        risk
        for risk in (get_address_risk(addr) for addr in _candidate_addresses())
        if risk.risk_score >= threshold
    ]
    risks.sort(key=lambda r: r.risk_score, reverse=True)
    return risks[:limit]


def risk_tier(score: float) -> str:
    """Bucket a fused score into the dashboard's three display tiers."""
    if score >= 0.8:
        return "Critical"
    if score >= 0.6:
        return "Review"
    return "Monitor"


def list_alerts(threshold: float = 0.8, limit: int = 50) -> list[Alert]:
    """Highest-risk addresses as alert records."""
    return [
        Alert(
            id=hashlib.sha1(risk.address.encode()).hexdigest()[:10],
            address=risk.address,
            risk_score=risk.risk_score,
            reason="Fused GNN + traffic-anomaly score above threshold",
            flagged_at=risk.last_updated,
        )
        for risk in _ranked_risks(threshold, limit)
    ]


def list_ranked_addresses(threshold: float = 0.0, limit: int = 50) -> list[RankedAddress]:
    """Highest-risk addresses for the dashboard's risk-ranked table.

    Same pool, same fused scores and same ordering as `list_alerts` -- this
    exposes the ranking as table rows instead of alert records, so the two
    panels cannot disagree about which addresses are riskiest.
    """
    return [
        RankedAddress(
            address=risk.address,
            risk_score=risk.risk_score,
            risk_tier=risk_tier(risk.risk_score),
            last_updated=risk.last_updated,
        )
        for risk in _ranked_risks(threshold, limit)
    ]


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
