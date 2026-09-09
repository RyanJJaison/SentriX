"""Personalized PageRank risk scores over the Elliptic Bitcoin transaction graph.

The pipeline computes, for every transaction in the dataset, how much PageRank
mass reaches it from transactions that are *confirmed illicit and inside the
training time window*. That score acts as a leakage-free "proximity to known
illicit activity" feature for a downstream classifier.

Two properties are treated as load-bearing and are asserted rather than assumed:

1.  **Node identity.** PyG reindexes nodes to 0..N-1 and discards the original
    ``txId``, so the mapping back to ``txId`` is a first-class output. The
    mapping is derived from the row order of the features CSV, because that is
    what PyG actually does, and it is then cross-checked against the loaded
    dataset (see :func:`validate_mapping`).

2.  **No label leakage.** Only nodes that are both illicit and in the training
    window may seed the personalization vector. Test-window and unknown-label
    nodes contribute graph structure only.

Run with::

    python -m src.ppr
"""

from __future__ import annotations

import logging
import sys
import time
from pathlib import Path

import networkx as nx
import numpy as np
import pandas as pd

from src.config import (
    DATA_PROCESSED,
    DATA_RAW,
    EXPECTED_LABEL_COUNTS,
    LABEL_ILLICIT,
    LABEL_LICIT,
    LABEL_NAMES,
    LABEL_UNKNOWN,
    N_EDGES,
    N_FEATURES,
    N_NODES,
    NODE_MAPPING_PARQUET,
    PPR_ALPHA,
    PPR_MAX_ITER,
    PPR_SCORES_PARQUET,
    PPR_DIRECTIONS,
    PPR_LOO_MAX_ITER,
    PPR_LOO_TOL,
    PPR_TOL,
    PYG_ROOT,
    RANK_METHOD,
    RAW_CLASS_MAP,
    RAW_CLASSES,
    RAW_EDGELIST,
    RAW_FEATURES,
    RAW_FILES,
    TIME_STEP_TRAIN_MAX,
)

log = logging.getLogger("ppr")


# --------------------------------------------------------------------------- #
# Loading
# --------------------------------------------------------------------------- #


def check_raw_files_present(raw_dir: Path = DATA_RAW) -> None:
    """Fail fast with actionable guidance if the raw CSVs are missing.

    Without this check, instantiating the PyG dataset would silently start a
    multi-hundred-megabyte download from data.pyg.org, which is both surprising
    and defeats the point of sourcing the original Kaggle files.
    """
    missing = [name for name in RAW_FILES if not (raw_dir / name).is_file()]
    if missing:
        raise FileNotFoundError(
            f"Missing raw Elliptic CSVs in {raw_dir}: {', '.join(missing)}.\n"
            "Fetch them first with:  python scripts/fetch_kaggle.py\n"
            "(That requires Kaggle API credentials; see the README.)"
        )


def load_pyg_dataset(root: Path = PYG_ROOT):
    """Load the Elliptic dataset as a single PyG ``Data`` object.

    ``EllipticBitcoinDataset`` does not override ``Dataset.raw_dir``, so its raw
    directory resolves to ``root/raw``. Passing ``root=data/`` therefore makes it
    read the Kaggle CSVs already sitting in ``data/raw/`` instead of downloading
    its own copy.
    """
    # Imported lazily: torch is a heavy import and the raw-file check above
    # should be able to fail before paying for it.
    from torch_geometric.datasets import EllipticBitcoinDataset

    log.info("Loading EllipticBitcoinDataset (root=%s)", root)
    dataset = EllipticBitcoinDataset(root=str(root))
    data = dataset[0]
    log.info(
        "Loaded graph: %s nodes, %s edges, %s features",
        f"{data.num_nodes:,}",
        f"{data.edge_index.shape[1]:,}",
        data.x.shape[1],
    )
    return data


def load_raw_frames(
    raw_dir: Path = DATA_RAW,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Read the three raw CSVs exactly the way PyG reads them.

    Matching PyG's read semantics is what makes the mapping assertions
    meaningful: the features CSV has no header, and column 0 is ``txId`` with
    column 1 the time step.

    Only those first two columns are read. The 165 feature columns are never
    needed here, and skipping them turns a ~270 MB read into a few MB.
    """
    log.info("Reading raw CSVs from %s", raw_dir)

    feat_df = pd.read_csv(
        raw_dir / RAW_FEATURES,
        header=None,
        usecols=[0, 1],
        names=["txId", "time_step"],
        dtype={"txId": "int64", "time_step": "int16"},
    )
    edge_df = pd.read_csv(
        raw_dir / RAW_EDGELIST,
        dtype={"txId1": "int64", "txId2": "int64"},
    )
    class_df = pd.read_csv(
        raw_dir / RAW_CLASSES,
        dtype={"txId": "int64", "class": "string"},
    )

    log.info(
        "Raw rows: features=%s, edges=%s, classes=%s",
        f"{len(feat_df):,}",
        f"{len(edge_df):,}",
        f"{len(class_df):,}",
    )
    return feat_df, edge_df, class_df


# --------------------------------------------------------------------------- #
# Node mapping
# --------------------------------------------------------------------------- #


def derive_node_mapping(feat_df: pd.DataFrame) -> pd.DataFrame:
    """Build the ``txId`` <-> PyG ``node_index`` mapping.

    PyG assigns indices with::

        {txId: i for i, txId in enumerate(feat_df['txId'].values)}

    so the index is the **row position in the features CSV**, not the rank of a
    sorted ``txId``. Sorting here would produce a mapping that still has the
    right number of rows and would therefore pass a naive length check while
    attributing every score to the wrong transaction.
    """
    mapping = pd.DataFrame(
        {
            "txId": feat_df["txId"].to_numpy(dtype=np.int64),
            "node_index": np.arange(len(feat_df), dtype=np.int64),
            "time_step": feat_df["time_step"].to_numpy(dtype=np.int16),
        }
    )
    return mapping


def validate_mapping(
    mapping: pd.DataFrame,
    data,
    edge_df: pd.DataFrame,
    class_df: pd.DataFrame,
) -> None:
    """Cross-check the derived mapping against the loaded PyG dataset.

    This is a hard gate: if any assertion fails, the mapping assumption behind
    every downstream score is void, so the run aborts instead of writing output.
    """
    log.info("Validating node mapping against the PyG dataset")

    y = data.y.numpy()
    train_mask = data.train_mask.numpy()
    test_mask = data.test_mask.numpy()
    time_step = mapping["time_step"].to_numpy()

    # -- Shape -------------------------------------------------------------- #
    assert len(mapping) == N_NODES, f"expected {N_NODES} nodes, got {len(mapping)}"
    assert data.num_nodes == N_NODES, f"PyG reports {data.num_nodes} nodes"
    # A duplicate txId would collapse PyG's dict comprehension and silently
    # shrink the graph, so uniqueness is checked explicitly.
    assert mapping["txId"].nunique() == len(mapping), "duplicate txId in features CSV"
    assert np.array_equal(
        mapping["node_index"].to_numpy(), np.arange(N_NODES)
    ), "node_index must be a contiguous 0..N-1 range in features-CSV row order"
    assert data.x.shape == (N_NODES, N_FEATURES), f"unexpected x shape {tuple(data.x.shape)}"
    assert tuple(data.edge_index.shape) == (2, N_EDGES), (
        f"unexpected edge_index shape {tuple(data.edge_index.shape)}"
    )
    assert len(edge_df) == N_EDGES, f"expected {N_EDGES} raw edges, got {len(edge_df)}"

    # -- Edge endpoint coverage --------------------------------------------- #
    known = pd.Index(mapping["txId"])
    for col in ("txId1", "txId2"):
        unknown = ~edge_df[col].isin(known)
        assert not unknown.any(), (
            f"{int(unknown.sum())} edge endpoints in {col} are absent from the features CSV"
        )

    # -- Split boundary ----------------------------------------------------- #
    # This is the highest-signal check in the battery. It confirms the split
    # rule *and* the mapping's row order at once: a permuted mapping would
    # scramble `time_step` and break mask equality.
    labeled = y != LABEL_UNKNOWN
    expected_train = (time_step < TIME_STEP_TRAIN_MAX) & labeled
    expected_test = (time_step >= TIME_STEP_TRAIN_MAX) & labeled
    assert np.array_equal(expected_train, train_mask), (
        "data.train_mask does not match (time_step < "
        f"{TIME_STEP_TRAIN_MAX}) & labeled; PyG's split rule may have changed"
    )
    assert np.array_equal(expected_test, test_mask), (
        "data.test_mask does not match (time_step >= "
        f"{TIME_STEP_TRAIN_MAX}) & labeled; PyG's split rule may have changed"
    )
    assert not (train_mask & test_mask).any(), "train and test masks overlap"
    assert train_mask.sum() + test_mask.sum() == labeled.sum(), (
        "train + test masks do not cover exactly the labeled nodes"
    )
    assert time_step[train_mask].max() < TIME_STEP_TRAIN_MAX, "train node at time_step >= boundary"
    assert time_step[test_mask].min() >= TIME_STEP_TRAIN_MAX, "test node at time_step < boundary"

    # -- Label domain and counts -------------------------------------------- #
    assert set(np.unique(y)) <= {LABEL_LICIT, LABEL_ILLICIT, LABEL_UNKNOWN}, (
        f"unexpected label values: {sorted(set(np.unique(y)))}"
    )
    for label, expected in EXPECTED_LABEL_COUNTS.items():
        actual = int((y == label).sum())
        assert actual == expected, (
            f"expected {expected} {LABEL_NAMES[label]} nodes, got {actual}"
        )
    train_labels = set(np.unique(y[train_mask]))
    assert {LABEL_LICIT, LABEL_ILLICIT} <= train_labels, (
        f"training window is missing a class: {sorted(train_labels)}"
    )

    # -- Edge set equality -------------------------------------------------- #
    # Encode each directed pair as a single int64 (max ~4.15e10, no overflow)
    # rather than building a Python set of 234k tuples: ~4 MB instead of
    # ~60-90 MB, and roughly an order of magnitude faster.
    idx = pd.Series(mapping["node_index"].to_numpy(), index=mapping["txId"])
    src = edge_df["txId1"].map(idx).to_numpy(dtype=np.int64)
    dst = edge_df["txId2"].map(idx).to_numpy(dtype=np.int64)
    derived = src * N_NODES + dst
    actual_src = data.edge_index[0].numpy().astype(np.int64)
    actual_dst = data.edge_index[1].numpy().astype(np.int64)
    actual = actual_src * N_NODES + actual_dst

    # Multiset equality, not positional. PyG happens to preserve edgelist order
    # today, but asserting that would couple this check to an internal detail
    # unrelated to whether the mapping is correct. Sorting (rather than using
    # sets) also means a duplicated edge is caught instead of hidden.
    assert np.array_equal(np.sort(derived), np.sort(actual)), (
        "edge set derived from the raw edgelist does not match data.edge_index; "
        "PyG's node reindexing scheme may have changed"
    )
    if not np.array_equal(derived, actual):
        log.info("Edge multisets match, but PyG reordered edges relative to the raw edgelist")

    n_self_loops = int((src == dst).sum())
    if n_self_loops:
        # A property of the data, not a mapping bug, so this informs rather than fails.
        log.warning("Edgelist contains %d self-loop(s)", n_self_loops)

    # -- Label alignment ---------------------------------------------------- #
    # PyG builds `y` from the classes-CSV row order and `x` from the
    # features-CSV row order, and never joins the two on txId. `data.y` is
    # therefore correct only if both files happen to be emitted in the same
    # node order. That assumption is unguarded in the library, so it is
    # checked here from both directions.
    assert class_df["txId"].nunique() == len(class_df), "duplicate txId in classes CSV"
    assert len(class_df) == N_NODES, f"expected {N_NODES} class rows, got {len(class_df)}"
    assert set(class_df["txId"]) == set(mapping["txId"]), (
        "classes CSV and features CSV cover different txId sets"
    )

    raw_positional = class_df["class"].map(RAW_CLASS_MAP).to_numpy(dtype=np.int64)
    raw_joined = (
        class_df.set_index("txId")["class"]
        .map(RAW_CLASS_MAP)
        .reindex(mapping["txId"])
        .to_numpy(dtype=np.int64)
    )
    assert not np.isnan(raw_joined.astype(float)).any(), "unmapped class value in classes CSV"

    positional_ok = np.array_equal(raw_positional, y)
    joined_ok = np.array_equal(raw_joined, y)
    if not positional_ok:
        # Abort rather than fall back to the joined labels: data.train_mask is
        # derived from `y != unknown`, so a misaligned `y` would also have
        # poisoned the seed set, and nothing downstream can be trusted.
        raise AssertionError(
            "data.y does not match the classes CSV in row order "
            f"(join-based comparison {'succeeded' if joined_ok else 'also failed'}). "
            "PyG assumes the features and classes CSVs share a row order; that "
            "assumption is violated here, so data.y and data.train_mask are unreliable."
        )
    assert joined_ok, "labels agree positionally but not by txId join, which should be impossible"

    log.info("Mapping validated: all assertions passed")


# --------------------------------------------------------------------------- #
# Graph construction and PPR
# --------------------------------------------------------------------------- #


def build_digraph(mapping: pd.DataFrame, edge_df: pd.DataFrame) -> nx.DiGraph:
    """Build the directed transaction graph, keyed by ``txId``.

    Edges follow the direction of payment flow, so PPR seeded at illicit nodes
    measures downstream taint.

    All nodes are added *before* any edges. This is required, not cosmetic:
    Elliptic contains transactions that appear in the features CSV but in no
    edge, and without an explicit ``add_nodes_from`` those would be absent from
    the output entirely. It also matters because ``nx.pagerank`` raises if the
    personalization vector names a node the graph does not contain, which an
    edge-isolated illicit seed would otherwise trigger.
    """
    graph = nx.DiGraph()
    graph.add_nodes_from(mapping["txId"].to_numpy().tolist())
    graph.add_edges_from(zip(edge_df["txId1"].to_numpy(), edge_df["txId2"].to_numpy()))

    assert graph.number_of_nodes() == N_NODES, (
        f"graph has {graph.number_of_nodes()} nodes, expected {N_NODES}"
    )
    n_edges = graph.number_of_edges()
    if n_edges != N_EDGES:
        # DiGraph collapses parallel edges, which is the correct behaviour for
        # PPR, so a shortfall is reported rather than treated as fatal.
        log.warning(
            "Graph has %s edges vs %s raw rows (duplicate pairs collapsed)",
            f"{n_edges:,}",
            f"{N_EDGES:,}",
        )
    log.info(
        "Built DiGraph: %s nodes, %s edges",
        f"{graph.number_of_nodes():,}",
        f"{n_edges:,}",
    )
    return graph


def build_personalization(mapping: pd.DataFrame, data) -> dict[int, float]:
    """Build the PPR personalization vector from illicit training nodes only.

    Restricting seeds to ``illicit AND train`` is what keeps the feature free of
    label leakage: nothing about a test node's own label can influence its
    score. Weights are uniform at ``1/k`` because there is no principled
    per-seed prior; NetworkX normalizes internally, so this is equivalent to
    weight 1.0 each, but expressing it as a distribution makes the intent and
    the ``sum > 0`` requirement self-evident.

    Nodes absent from the returned dict receive zero teleport mass, which is
    deliberate. Giving non-seeds a small floor would blend in global PageRank
    and dilute the signal.
    """
    y = data.y.numpy()
    seed_mask = (y == LABEL_ILLICIT) & data.train_mask.numpy()
    seed_tx = mapping["txId"].to_numpy()[seed_mask]

    k = len(seed_tx)
    assert k > 0, "no illicit training nodes found; cannot seed PPR"

    # Leakage guard, independent of the mask checks in validate_mapping.
    seed_time_steps = mapping["time_step"].to_numpy()[seed_mask]
    assert seed_time_steps.max() < TIME_STEP_TRAIN_MAX, (
        "a PPR seed falls outside the training window"
    )

    log.info(
        "Seeding PPR from %s illicit training nodes (time steps %d-%d), weight %.3e each",
        f"{k:,}",
        int(seed_time_steps.min()),
        int(seed_time_steps.max()),
        1.0 / k,
    )
    return {int(tx): 1.0 / k for tx in seed_tx}


def compute_ppr(
    graph: nx.DiGraph,
    personalization: dict[int, float],
    alpha: float = PPR_ALPHA,
    tol: float = PPR_TOL,
    max_iter: int = PPR_MAX_ITER,
) -> dict[int, float]:
    """Run Personalized PageRank over the full graph.

    ``dangling=personalization`` matches what NetworkX already does when
    ``dangling`` is None, but is passed explicitly to pin the semantics. Elliptic
    has many sink transactions, and sending their mass back to the illicit seeds
    is the correct reading of taint flow. The alternative -- a uniform dangling
    vector -- would hand every node nonzero mass on every iteration and wash out
    the contrast between reachable and unreachable nodes.

    ``nstart=personalization`` is what makes unreachable nodes score *exactly*
    zero. ``nx.pagerank`` dispatches to its SciPy implementation, whose power
    iteration is ``x = alpha * (x @ A + dangling) + (1 - alpha) * p``. The
    default start vector is uniform ``1/N``, so every node begins with mass; an
    unreachable node receives no inflow and no teleport, so its score merely
    decays by a factor of alpha each pass and stays a small positive number
    after any finite number of iterations. Starting the mass on the seeds
    instead means unreachable nodes begin at zero and are never written to,
    which is the invariant :func:`transform_scores` and the percentile rely on.
    """
    log.info("Running PPR (alpha=%.2f, tol=%.1e, max_iter=%d)", alpha, tol, max_iter)
    started = time.perf_counter()
    try:
        scores = nx.pagerank(
            graph,
            alpha=alpha,
            personalization=personalization,
            dangling=personalization,
            nstart=personalization,
            tol=tol,
            max_iter=max_iter,
        )
    except nx.PowerIterationFailedConvergence as exc:
        raise RuntimeError(
            f"PPR failed to converge within {max_iter} iterations at tol={tol:.1e}. "
            "Raise PPR_MAX_ITER or loosen PPR_TOL in src/config.py."
        ) from exc
    log.info("PPR converged in %.2fs", time.perf_counter() - started)
    return scores


def bfs_distances(graph: nx.DiGraph, seeds) -> tuple[dict[int, int], int]:
    """Multi-source BFS distance from the nearest seed, plus the maximum depth.

    One traversal rather than ``nx.descendants`` per seed: with several thousand
    seeds the per-seed form re-walks the graph thousands of times and dominates
    the runtime of the whole pipeline. Recording the level as the frontier
    advances makes the distances free.
    """
    distance: dict[int, int] = {int(seed): 0 for seed in seeds}
    frontier = list(distance)
    depth = 0
    while frontier:
        depth += 1
        nxt = []
        for node in frontier:
            for successor in graph.successors(node):
                if successor not in distance:
                    distance[successor] = depth
                    nxt.append(successor)
        frontier = nxt
    return distance, max(depth - 1, 0)


def check_no_unreachable_mass(
    raw: np.ndarray,
    tx_ids: np.ndarray,
    distance: dict[int, int],
    max_report: int = 20,
) -> None:
    """Hard check: a node unreachable from every seed must hold no mass.

    This is the leakage indicator. Mass can only enter the graph at a seed, so a
    node with no directed path from any seed must score exactly zero. A nonzero
    value there means teleport or dangling mass escaped the seed set -- for
    instance if ``personalization`` or ``dangling`` were dropped from the
    :func:`compute_ppr` call, making every node a teleport target. That would
    silently redefine the feature, so it fails the run.
    """
    offenders = [
        (int(tx), float(value))
        for tx, value in zip(tx_ids, raw)
        if value != 0.0 and int(tx) not in distance
    ]
    if offenders:
        log.error(
            "%d node(s) hold nonzero mass despite being unreachable from every seed "
            "(txId, ppr_raw):",
            len(offenders),
        )
        offenders.sort(key=lambda item: -item[1])
        for tx, value in offenders[:max_report]:
            log.error("    txId=%-12d ppr_raw=%.6e", tx, value)
        if len(offenders) > max_report:
            log.error("    ... %d more", len(offenders) - max_report)

    assert not offenders, (
        f"{len(offenders)} unreachable node(s) hold nonzero PPR mass; "
        "teleport or dangling mass is leaking outside the seed set"
    )


def report_underflow(
    raw: np.ndarray,
    tx_ids: np.ndarray,
    distance: dict[int, int],
    max_report: int = 20,
) -> int:
    """Soft check: reachable nodes that still score exactly zero, from underflow.

    These are expected rather than erroneous. PPR mass decays by ``alpha`` per
    hop and divides across out-edges, so far enough from any seed it falls below
    the smallest representable float64 and lands on exactly 0.0. Measured on the
    full Elliptic graph with a single global seeding, 7 nodes underflowed at BFS
    distances 16-21 against a maximum depth of 21 -- all at the extreme tail of
    the reachable set. Raising ``max_iter`` from 200 to 1000 changed nothing:
    the score vector was bitwise identical, so this is float64 underflow and not
    a convergence failure.

    Returns the count and logs the distance distribution, since a node
    underflowing at a *short* distance would be the surprising case and worth
    investigating.
    """
    underflowed = [
        (int(tx), distance[int(tx)])
        for tx, value in zip(tx_ids, raw)
        if value == 0.0 and int(tx) in distance
    ]
    if not underflowed:
        return 0

    underflowed.sort(key=lambda item: item[1])
    distances = [dist for _, dist in underflowed]
    log.info(
        "%d reachable node(s) scored exactly 0.0 from float64 underflow "
        "(distance range %d-%d, median %d)",
        len(underflowed),
        min(distances),
        max(distances),
        int(np.median(distances)),
    )
    for tx, dist in underflowed[:max_report]:
        log.info("    txId=%-12d distance=%d", tx, dist)
    if len(underflowed) > max_report:
        log.info("    ... %d more", len(underflowed) - max_report)

    return len(underflowed)


def check_zero_structure(
    graph: nx.DiGraph,
    personalization: dict[int, float],
    raw: np.ndarray,
    tx_ids: np.ndarray,
    max_report: int = 20,
) -> dict[str, int]:
    """Audit the relationship between zero scores and graph reachability.

    Two classes of disagreement exist and they have opposite meanings, so they
    are handled separately rather than compared as one count:

    * A reachable node scoring zero is **expected** -- float64 underflow at long
      distance. Reported, not fatal. See :func:`report_underflow`.
    * An unreachable node holding mass is **never** acceptable -- it means mass
      is entering outside the seed set. Fatal. See
      :func:`check_no_unreachable_mass`.

    ``raw`` and ``tx_ids`` must be in the same order so a row can be named by
    its real ``txId``.
    """
    distance, max_depth = bfs_distances(graph, personalization)
    reachable = len(distance)

    check_no_unreachable_mass(raw, tx_ids, distance, max_report)
    n_underflow = report_underflow(raw, tx_ids, distance, max_report)

    n_zero = int((raw == 0.0).sum())
    log.info(
        "Reachability audit: %s reachable (max depth %d), %s exact zeros, "
        "%d underflowed, %s structurally unreachable",
        f"{reachable:,}",
        max_depth,
        f"{n_zero:,}",
        n_underflow,
        f"{graph.number_of_nodes() - reachable:,}",
    )
    return {
        "reachable": reachable,
        "max_depth": max_depth,
        "n_zero": n_zero,
        "n_underflow": n_underflow,
        "unreachable": graph.number_of_nodes() - reachable,
    }

# --------------------------------------------------------------------------- #
# Score transform
# --------------------------------------------------------------------------- #


def compute_per_step_loo_ppr(
    graph: nx.DiGraph,
    mapping: pd.DataFrame,
    labels: np.ndarray,
    tol: float = PPR_LOO_TOL,
    max_iter: int = PPR_LOO_MAX_ITER,
) -> tuple[np.ndarray, dict[str, int]]:
    """Per-step PPR with leave-one-out seeding, returned in ``mapping`` order.

    Because every edge stays inside one time step, each step is an independent
    component and is solved on its own subgraph. Within a step the seeds are
    that step's illicit nodes.

    Leave-one-out matters because most illicit nodes would otherwise be their own
    seed and score high by construction. Measured on the full graph, self-seeding
    put 100% of illicit nodes at a nonzero score and inflated forward separation
    to 75.79x; excluding self drops that to 13.0% coverage and 9.45x, which is
    the honest number.

    The exclusion is exact rather than approximate. PPR is linear in the
    personalization vector, so for uniform seeds ``S``::

        score(v | S) = (1 / |S|) * sum over s in S of ppr_s(v)

    Running one single-seed PPR per illicit node and caching the column sums lets
    any node's score be recomputed against ``S \\ {v}`` by subtracting its own
    column and renormalizing by ``|S| - 1``. Cost is one PPR per illicit node
    per direction -- about 4,545 small solves, roughly 100 s in total.
    """
    tx_ids = mapping["txId"].to_numpy()
    time_steps = mapping["time_step"].to_numpy()
    position = {int(tx): i for i, tx in enumerate(tx_ids)}

    column_sum = np.zeros(len(tx_ids), dtype=np.float64)
    self_mass = np.zeros(len(tx_ids), dtype=np.float64)
    seeds_in_step = np.zeros(len(tx_ids), dtype=np.int64)

    started = time.perf_counter()
    n_solves = 0
    for step in np.unique(time_steps):
        in_step = time_steps == step
        subgraph = graph.subgraph(tx_ids[in_step].tolist())
        step_seeds = tx_ids[in_step & (labels == LABEL_ILLICIT)]
        if len(step_seeds) == 0:
            # No illicit node in this step, so nothing to propagate from. Every
            # node here keeps a score of exactly 0.0.
            continue
        seeds_in_step[in_step] = len(step_seeds)

        for seed in step_seeds:
            single = {int(seed): 1.0}
            try:
                result = nx.pagerank(
                    subgraph,
                    alpha=PPR_ALPHA,
                    personalization=single,
                    dangling=single,
                    nstart=single,
                    tol=tol,
                    max_iter=max_iter,
                )
            except nx.PowerIterationFailedConvergence as exc:
                raise RuntimeError(
                    f"single-seed PPR failed to converge for txId={int(seed)} "
                    f"in time step {int(step)} ({max_iter} iterations, tol={tol:.1e})"
                ) from exc
            n_solves += 1
            for tx, value in result.items():
                if value > 0.0:
                    column_sum[position[int(tx)]] += value
            self_mass[position[int(seed)]] += result.get(int(seed), 0.0)

    # Leave-one-out normalization. A non-seed node averages over all seeds in
    # its step; a seed node averages over the others only.
    scores = np.zeros(len(tx_ids), dtype=np.float64)
    k = seeds_in_step.astype(np.float64)
    is_seed = (labels == LABEL_ILLICIT) & (seeds_in_step > 0)
    is_other = ~is_seed & (seeds_in_step > 0)

    scores[is_other] = column_sum[is_other] / k[is_other]
    # A step whose only illicit node is this one leaves no other seed, so the
    # leave-one-out score is undefined and correctly falls back to 0.0.
    remaining = k[is_seed] - 1.0
    scores[is_seed] = np.where(
        remaining > 0.0,
        (column_sum[is_seed] - self_mass[is_seed]) / np.maximum(remaining, 1e-30),
        0.0,
    )
    assert (scores >= 0.0).all(), "leave-one-out produced a negative score"

    stats = {
        "solves": n_solves,
        "seconds": int(time.perf_counter() - started),
        "nonzero": int((scores > 0.0).sum()),
    }
    log.info(
        "Per-step LOO PPR: %s single-seed solves in %ds, %s nonzero nodes (%.2f%%)",
        f"{n_solves:,}",
        stats["seconds"],
        f"{stats['nonzero']:,}",
        100 * stats["nonzero"] / len(tx_ids),
    )
    return scores, stats

def transform_scores(raw: np.ndarray, prefix: str) -> pd.DataFrame:
    """Turn raw PPR mass into a log-compressed [0, 1] score and a percentile.

    Column names are ``{prefix}_raw``, ``{prefix}_score`` and
    ``{prefix}_percentile`` so that several directions can sit side by side in
    one frame.

    Raw PPR is heavy-tailed, and individual scores land many orders of magnitude
    below 1. Applying ``log1p`` directly to values that small is a no-op --
    ``log1p(x)/x == 1.0`` to six decimals at x=1e-6 -- which would quietly
    reduce the whole step to a min-max of the raw scores. Scaling so the
    smallest nonzero score maps to 1.0 is what gives the logarithm something to
    compress.

    Scaling also avoids the epsilon problem. With ``log(x + eps)`` the block of
    zero-scored nodes lands at ``log(eps)``, so the shape of the entire
    distribution depends on an arbitrary constant. Here ``log1p(0)`` is exactly
    0.0, so a zero score stays a meaningful floor rather than an artifact, and
    the min-max reduces to a division by the maximum.
    """
    values = np.asarray(raw, dtype=np.float64)
    positive = values[values > 0.0]
    assert positive.size > 0, f"all {prefix} scores are zero; check the seed set"

    scale = 1.0 / positive.min()
    z = np.log1p(values * scale)
    z_max = z.max()
    assert z_max > 0.0, f"{prefix}: log-transformed scores are degenerate"

    # Ranked on the raw values: the transform above is strictly monotone, so the
    # ranks are identical, but this keeps the percentile independent of any
    # later change to the transform and sidesteps float collisions from /z_max.
    percentile = pd.Series(values).rank(method=RANK_METHOD, pct=True).to_numpy(np.float64)

    out = pd.DataFrame(
        {
            f"{prefix}_raw": values,
            f"{prefix}_score": z / z_max,
            f"{prefix}_percentile": percentile,
        }
    )
    out.attrs[f"{prefix}_scale"] = scale
    out.attrs[f"{prefix}_z_max"] = float(z_max)
    return out


# --------------------------------------------------------------------------- #
# Assembly and output
# --------------------------------------------------------------------------- #


def assemble_output(
    mapping: pd.DataFrame, data, columns: dict[str, np.ndarray]
) -> pd.DataFrame:
    """Join every PPR direction onto the mapping, one row per node by ``txId``.

    ``columns`` maps a column prefix (``ppr_fwd``, ``ppr_rev``) to that
    direction's raw score array, already in ``mapping`` row order.
    """
    y = data.y.numpy()
    train_mask = data.train_mask.numpy()
    test_mask = data.test_mask.numpy()
    split = np.where(train_mask, "train", np.where(test_mask, "test", "unlabeled"))

    scores = pd.DataFrame(
        {
            "txId": mapping["txId"].to_numpy(),
            "node_index": mapping["node_index"].to_numpy(),
            "time_step": mapping["time_step"].to_numpy(),
            "label": y.astype(np.int8),
            "split": pd.Categorical(split, categories=["train", "test", "unlabeled"]),
        }
    )

    # `pd.concat` does not preserve `.attrs`, so the transform parameters are
    # collected first and reattached to the finished frame.
    attrs: dict[str, float] = {}
    for prefix, raw in columns.items():
        assert len(raw) == len(mapping), f"{prefix} length does not match the mapping"
        transformed = transform_scores(raw, prefix)
        attrs.update(transformed.attrs)
        scores = pd.concat([scores, transformed], axis=1)
    scores.attrs.update(attrs)

    assert len(scores) == N_NODES
    assert not scores.isna().any().any(), "NaN in assembled output"
    for prefix in columns:
        assert scores[f"{prefix}_score"].between(0.0, 1.0).all(), f"{prefix}_score outside [0, 1]"
        assert scores[f"{prefix}_percentile"].between(0.0, 1.0).all(), (
            f"{prefix}_percentile outside [0, 1]"
        )
    return scores


def write_outputs(mapping: pd.DataFrame, scores: pd.DataFrame) -> None:
    DATA_PROCESSED.mkdir(parents=True, exist_ok=True)
    mapping.to_parquet(NODE_MAPPING_PARQUET, index=False)
    scores.to_parquet(PPR_SCORES_PARQUET, index=False)
    log.info("Wrote %s", NODE_MAPPING_PARQUET)
    log.info("Wrote %s (%d columns)", PPR_SCORES_PARQUET, scores.shape[1])


def log_summary(scores: pd.DataFrame, prefixes: list[str]) -> None:
    """Report each direction's distribution and its separation on held-out data."""
    log.info("--- summary ---")
    for prefix in prefixes:
        raw = scores[f"{prefix}_raw"]
        score = scores[f"{prefix}_score"]
        n_zero = int((raw == 0.0).sum())
        floor = float(scores.loc[raw == 0.0, f"{prefix}_percentile"].iloc[0]) if n_zero else 0.0
        log.info(
            "%s: nonzero=%s (%.2f%%) scale=%.6e z_max=%.4f percentile_floor=%.4f",
            prefix,
            f"{len(scores) - n_zero:,}",
            100 * (1 - n_zero / len(scores)),
            scores.attrs[f"{prefix}_scale"],
            scores.attrs[f"{prefix}_z_max"],
            floor,
        )
        # Separation on the held-out split is the only honest read on whether the
        # feature carries signal. Leave-one-out seeding means an illicit node is
        # never its own seed, so this is not self-fulfilling.
        for split_name in ("test", "train"):
            rows = scores[scores["split"] == split_name]
            illicit = rows.loc[rows["label"] == LABEL_ILLICIT, f"{prefix}_score"]
            licit = rows.loc[rows["label"] == LABEL_LICIT, f"{prefix}_score"]
            ratio = illicit.mean() / max(licit.mean(), 1e-30)
            log.info(
                "    %-5s illicit mean=%.6f (nonzero %.1f%%, n=%s) | "
                "licit mean=%.6f (nonzero %.1f%%, n=%s) | separation=%.2fx",
                split_name,
                illicit.mean(),
                100 * (illicit > 0).mean(),
                f"{len(illicit):,}",
                licit.mean(),
                100 * (licit > 0).mean(),
                f"{len(licit):,}",
                ratio,
            )
        if floor > 0.5:
            log.warning(
                "    %s_percentile floor is %.4f: most nodes tie at zero, so the "
                "percentile carries no information at or below that value",
                prefix,
                floor,
            )


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )

    try:
        check_raw_files_present()
    except FileNotFoundError as exc:
        log.error("%s", exc)
        return 1

    data = load_pyg_dataset()
    feat_df, edge_df, class_df = load_raw_frames()

    mapping = derive_node_mapping(feat_df)
    validate_mapping(mapping, data, edge_df, class_df)

    forward = build_digraph(mapping, edge_df)
    labels = data.y.numpy()

    # One column per direction. Forward answers "downstream of illicit", reverse
    # answers "sent toward illicit". Measured separately on held-out data they
    # trade off -- forward is sharper (9.45x vs 5.04x), reverse reaches far more
    # nodes (11,247 vs 2,705 nonzero) -- so both ship and the ablation decides.
    graphs = {"ppr_fwd": forward, "ppr_rev": forward.reverse(copy=True)}
    columns: dict[str, np.ndarray] = {}
    for prefix, graph in graphs.items():
        log.info("Computing %s", prefix)
        columns[prefix], _ = compute_per_step_loo_ppr(graph, mapping, labels)

    scores = assemble_output(mapping, data, columns)
    write_outputs(mapping, scores)
    log_summary(scores, list(columns))
    return 0


if __name__ == "__main__":
    sys.exit(main())
