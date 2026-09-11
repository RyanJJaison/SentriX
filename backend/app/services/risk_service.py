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
import csv
import hashlib
import json
import logging
import os
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

from app.models.schemas import Alert, AddressRisk, GraphEdge, GraphNode, OverviewStats, RankedAddress, RiskFactors, SubgraphResponse
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


# Elliptic edge list (raw Kaggle release), used for real subgraph structure.
# Overridable so tests and deployments can point at a different file.
_DEFAULT_EDGELIST_PATH = Path(__file__).resolve().parents[3] / "data" / "raw" / "elliptic_txs_edgelist.csv"

# Ceiling on nodes returned by one subgraph query, center included. Elliptic has
# addresses with hundreds of direct neighbours; returning all of them makes an
# unreadable blob in the UI and a large payload for the AI tool. When the real
# neighbourhood exceeds this, the highest-risk neighbours are kept.
_SUBGRAPH_NODE_CAP = 40


def _edgelist_path() -> Path:
    override = os.environ.get("SENTRIX_EDGELIST_PATH")
    return Path(override) if override else _DEFAULT_EDGELIST_PATH


@lru_cache(maxsize=1)
def _load_adjacency() -> dict[str, frozenset[str]]:
    """Load the Elliptic edge list into {txId: frozenset(connected txIds)}.

    Built **undirected**: each edge is recorded in both directions. The
    underlying data is directed (txId1 -> txId2), but a subgraph view is asking
    "what is this transaction connected to", and hiding inbound edges would show
    an analyst a misleadingly sparse neighbourhood.

    Cached for the process lifetime like `_load_graph_scores`: ~234k edges
    parsed once into an adjacency map rather than re-read per request.

    A missing file is not an error -- callers fall back to a center-only
    response, which keeps the API working without the raw dataset.
    """
    path = _edgelist_path()
    if not path.is_file():
        log.warning(
            "Edge list not found at %s; subgraph queries will return the center "
            "node only. Fetch it with `python scripts/fetch_kaggle.py`.",
            path,
        )
        return {}

    neighbours: dict[str, set[str]] = {}
    skipped = 0
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        # Column names verified against the file itself, not assumed.
        if reader.fieldnames != ["txId1", "txId2"]:
            log.warning(
                "Unexpected edge list columns %s (expected ['txId1', 'txId2']); "
                "subgraph queries will return the center node only.",
                reader.fieldnames,
            )
            return {}
        for row in reader:
            source, target = row.get("txId1"), row.get("txId2")
            if not source or not target:
                skipped += 1
                continue
            neighbours.setdefault(source, set()).add(target)
            neighbours.setdefault(target, set()).add(source)

    log.info(
        "Loaded adjacency for %d addresses from %s%s",
        len(neighbours),
        path,
        f" ({skipped} rows skipped)" if skipped else "",
    )
    return {node: frozenset(peers) for node, peers in neighbours.items()}


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


def top_ranked_addresses(limit: int = 50) -> list[str]:
    """The addresses the dashboard currently ranks highest, by *fused* score.

    Exposed for the rescoring scheduler so each cycle refreshes exactly what
    users are looking at. Ranking by fused score matters: `_candidate_addresses`
    orders by the exported GNN term alone, and once the live traffic component
    starts moving, the two orderings diverge -- an address can sit in the UI's
    top 25 while falling outside a GNN-ranked top 50, which would leave it
    frozen, the very bug this feeds.

    Reads through `_ranked_risks`, so cached entries are returned as-is (cheap)
    and only genuinely new addresses are fused here. The caller then overwrites
    every returned address via `rescore_neighborhood`.
    """
    return [risk.address for risk in _ranked_risks(threshold=0.0, limit=limit)]


# Tier cutoffs, named so the overview card and the table agree by construction
# rather than by two copies of the same literal.
CRITICAL_THRESHOLD = 0.8
REVIEW_THRESHOLD = 0.6


def risk_tier(score: float) -> str:
    """Bucket a fused score into the dashboard's three display tiers."""
    if score >= CRITICAL_THRESHOLD:
        return "Critical"
    if score >= REVIEW_THRESHOLD:
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


def _edge_id(source: str, target: str) -> str:
    """Stable synthetic id for one edge.

    Not a blockchain transaction hash, and not pretending to be one. Elliptic's
    public release identifies transactions by anonymised synthetic ids rather
    than real hashes -- that is a property of the dataset, not a gap to fill --
    so no real hash exists to put here for an *edge* either. This is a stable
    key derived from the endpoint pair, so the same edge always carries the same
    id across requests (useful for React keys and diffing). Order-independent,
    because the adjacency map is undirected and the same edge can be traversed
    from either side.
    """
    low, high = sorted((source, target))
    return hashlib.sha1(f"{low}->{high}".encode()).hexdigest()[:16]


# Held-out test metrics for the shipped GraphSAGE checkpoint, from
# data/processed/ablation.md (enriched config, mean over seeds 42/1337/2024).
# Hardcoded deliberately: these are properties of a trained model artefact, not
# a runtime measurement, and they only change when the model is retrained. The
# source file is the ablation table those numbers were verified against.
MODEL_TEST_AUC = 0.9570
MODEL_TEST_F1 = 0.6943


def get_overview_stats() -> OverviewStats:
    """Aggregate counters for the dashboard's summary cards.

    `addresses_monitored` is the full exported dataset. `high_risk_count`,
    however, is counted over the fused candidate pool rather than all ~204k
    addresses: the fused score includes the live traffic term, so a true
    dataset-wide count would mean fusing every address on every request. The
    pool is the same one the alerts feed and ranked table draw from, and
    `high_risk_scanned` reports how many addresses were actually examined so
    the count can be presented honestly rather than implying a full scan.

    `high_risk_count` is live: it moves as the rescoring loop refreshes traffic
    components and addresses cross the tier threshold.
    """
    graph_scores = _load_graph_scores()
    scanned = _candidate_addresses()
    high_risk = sum(
        1 for addr in scanned if get_address_risk(addr).risk_score >= CRITICAL_THRESHOLD
    )
    return OverviewStats(
        addresses_monitored=len(graph_scores),
        high_risk_count=high_risk,
        high_risk_scanned=len(scanned),
        critical_threshold=CRITICAL_THRESHOLD,
        model_test_auc=MODEL_TEST_AUC,
        model_test_f1=MODEL_TEST_F1,
    )


def get_subgraph(address: str, depth: int = 1) -> SubgraphResponse:
    """Real Elliptic neighbourhood around `address`, BFS to `depth` hops.

    Structure comes from the raw edge list via `_load_adjacency`; per-node risk
    comes from `get_address_risk`, so both are real rather than derived from the
    requested id.

    An address with no edges in the dataset returns just itself with no edges.
    Elliptic genuinely contains such nodes, and an empty neighbourhood is the
    honest answer -- neighbours are never fabricated to make the response look
    populated.

    When the real neighbourhood is larger than `_SUBGRAPH_NODE_CAP`, the
    highest-risk nodes are kept, so truncation drops the least interesting
    nodes rather than an arbitrary slice.
    """
    adjacency = _load_adjacency()
    center_score = get_address_risk(address).risk_score

    # BFS outward, recording the hop at which each node is first reached.
    hops: dict[str, int] = {address: 0}
    frontier = [address]
    for hop in range(1, depth + 1):
        next_frontier: list[str] = []
        for node in frontier:
            for peer in adjacency.get(node, frozenset()):
                if peer not in hops:
                    hops[peer] = hop
                    next_frontier.append(peer)
        if not next_frontier:
            break
        frontier = next_frontier

    discovered = [node for node in hops if node != address]

    # Cap by risk, not by traversal order: score every discovered node, keep the
    # riskiest. Nearer hops win ties so a 1-hop neighbour is preferred over an
    # equally-risky 2-hop one.
    scores = {node: get_address_risk(node).risk_score for node in discovered}
    if len(discovered) > _SUBGRAPH_NODE_CAP - 1:
        discovered.sort(key=lambda node: (-scores[node], hops[node]))
        discovered = discovered[: _SUBGRAPH_NODE_CAP - 1]

    kept = {address, *discovered}
    nodes = [GraphNode(id=address, label=address, risk_score=center_score)]
    nodes.extend(
        GraphNode(id=node, label=node, risk_score=scores[node]) for node in discovered
    )

    # Emit each edge once, only where both endpoints survived the cap.
    seen: set[tuple[str, str]] = set()
    edges: list[GraphEdge] = []
    for node in kept:
        for peer in adjacency.get(node, frozenset()):
            if peer not in kept:
                continue
            pair = (node, peer) if node < peer else (peer, node)
            if pair in seen:
                continue
            seen.add(pair)
            edges.append(GraphEdge(source=pair[0], target=pair[1], tx_id=_edge_id(*pair)))

    return SubgraphResponse(center=address, depth=depth, nodes=nodes, edges=edges)


def rescore_neighborhood(changed_addresses: list[str]) -> int:
    """Incrementally recompute scores for a set of addresses (Technical
    Architecture §3.7: PPR + GNN inference on the local neighborhood only,
    not the full graph). Returns the number of addresses rescored."""
    for address in changed_addresses:
        _score_cache[address] = _compute_address_risk(address)
    return len(changed_addresses)
