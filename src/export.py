"""Export per-node risk records to output/scores.jsonl, one JSON object per line.

Scores come from the trained GraphSAGE checkpoint; graph context comes from the
PPR parquet and the edge list. Every labeled and unlabeled node is exported, so
downstream consumers can score any transaction in the dataset.

``contributing_factors`` intentionally carries a single entry, ``gnn_score`` at
weight 1.0. The fusion engine adds further factors (traffic_anomaly and others)
later; this file does not model them.

Run with::

    python -m src.export
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import torch

from src.config import (
    DATA_PROCESSED,
    LABEL_ILLICIT,
    PPR_SCORES_PARQUET,
    PROJECT_ROOT,
    PYG_ROOT,
)
from src.train import CHECKPOINT_DIR, GraphSAGE, standardize

log = logging.getLogger("export")

OUTPUT_DIR = PROJECT_ROOT / "output"
SCORES_JSONL = OUTPUT_DIR / "scores.jsonl"

MODEL_VERSION = "gnn-ppr-v0.1"

# Risk tier cut points on the GNN illicit probability.
TIER_MEDIUM = 0.3
TIER_HIGH = 0.7


def risk_tier(score: float) -> str:
    """Bucket a probability into low / medium / high at 0.3 and 0.7."""
    if score >= TIER_HIGH:
        return "high"
    if score >= TIER_MEDIUM:
        return "medium"
    return "low"


def load_checkpoint(name: str = "enriched"):
    path = CHECKPOINT_DIR / f"graphsage_{name}.pt"
    if not path.is_file():
        raise FileNotFoundError(
            f"{path} not found. Run `python -m src.train` first to train the model."
        )
    return torch.load(path, weights_only=False), path


@torch.no_grad()
def score_all_nodes(checkpoint: dict) -> np.ndarray:
    """Run the trained model over the whole graph and return illicit probabilities."""
    from torch_geometric.datasets import EllipticBitcoinDataset

    from src.features import ENRICHED_FEATURES_PT

    data = EllipticBitcoinDataset(root=str(PYG_ROOT))[0]

    if checkpoint["raw_only"]:
        x = data.x.float()
    else:
        bundle = torch.load(ENRICHED_FEATURES_PT, weights_only=False)
        x = bundle["x"].float()

    # Standardize with the same training-node statistics used during fitting, so
    # inference sees the distribution the model was trained on.
    x = standardize(x, data.train_mask)

    model = GraphSAGE(
        in_dim=checkpoint["in_dim"],
        hidden_dim=checkpoint["hidden_dim"],
        n_layers=checkpoint["n_layers"],
        dropout=checkpoint["dropout"],
    )
    model.load_state_dict(checkpoint["state_dict"])
    model.eval()

    prob = torch.sigmoid(model(x, data.edge_index)).cpu().numpy().astype(np.float64)
    assert len(prob) == data.num_nodes
    assert np.isfinite(prob).all(), "non-finite probability from the model"
    return prob, data


def neighbor_stats(data, labels: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Per-node total neighbour count and confirmed-illicit neighbour count.

    Neighbours are counted on the undirected view: a transaction's context
    includes both what it paid and what paid it. ``known_illicit_neighbors``
    counts neighbours labeled illicit in the dataset -- ground truth, not model
    output -- so a consumer can tell an evidenced neighbourhood from an inferred
    one.
    """
    n_nodes = data.num_nodes
    src = data.edge_index[0].numpy()
    dst = data.edge_index[1].numpy()

    degree = np.zeros(n_nodes, dtype=np.int64)
    np.add.at(degree, src, 1)
    np.add.at(degree, dst, 1)

    illicit = (labels == LABEL_ILLICIT).astype(np.int64)
    illicit_neighbors = np.zeros(n_nodes, dtype=np.int64)
    # An edge contributes to each endpoint's count if the other endpoint is illicit.
    np.add.at(illicit_neighbors, src, illicit[dst])
    np.add.at(illicit_neighbors, dst, illicit[src])

    return degree, illicit_neighbors


def build_records(
    scores_df: pd.DataFrame,
    prob: np.ndarray,
    degree: np.ndarray,
    illicit_neighbors: np.ndarray,
    scored_at: str,
) -> list[dict]:
    """Assemble one record per node, keyed to the real ``txId``.

    The PPR parquet carries ``node_index``, so it is used to align the
    model-order arrays to each row rather than assuming the parquet and the
    tensors share a row order.
    """
    index = scores_df["node_index"].to_numpy()
    records = []
    for row, node_index in zip(scores_df.itertuples(index=False), index):
        score = float(prob[node_index])
        records.append(
            {
                "address_id": str(row.txId),
                "risk_score": round(score, 6),
                "risk_tier": risk_tier(score),
                "contributing_factors": [
                    {
                        "name": "gnn_score",
                        "value": round(score, 6),
                        "weight": 1.0,
                        # Single-factor model, so the contribution is the whole
                        # score. The fusion engine reweights once it adds more.
                        "contribution": round(score, 6),
                    }
                ],
                "graph_context": {
                    "ppr_score": round(float(row.ppr_fwd_score), 6),
                    "ppr_percentile": round(float(row.ppr_fwd_percentile), 6),
                    "neighbor_count": int(degree[node_index]),
                    "known_illicit_neighbors": int(illicit_neighbors[node_index]),
                },
                "model_version": MODEL_VERSION,
                "scored_at": scored_at,
            }
        )
    return records


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--checkpoint",
        default="enriched",
        help="checkpoint name under data/processed/checkpoints (default: enriched)",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )

    try:
        checkpoint, path = load_checkpoint(args.checkpoint)
    except FileNotFoundError as exc:
        log.error("%s", exc)
        return 1
    log.info("Loaded checkpoint %s (best epoch %d)", path, checkpoint["best_epoch"])

    if not PPR_SCORES_PARQUET.is_file():
        log.error("%s not found. Run `python -m src.ppr` first.", PPR_SCORES_PARQUET)
        return 1
    scores_df = pd.read_parquet(PPR_SCORES_PARQUET)

    prob, data = score_all_nodes(checkpoint)
    labels = data.y.numpy()
    degree, illicit_neighbors = neighbor_stats(data, labels)

    scored_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    records = build_records(scores_df, prob, degree, illicit_neighbors, scored_at)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with SCORES_JSONL.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record) + "\n")

    tiers = pd.Series([r["risk_tier"] for r in records]).value_counts()
    log.info("Wrote %s records to %s", f"{len(records):,}", SCORES_JSONL)
    log.info(
        "Tier distribution: high=%s medium=%s low=%s",
        f"{int(tiers.get('high', 0)):,}",
        f"{int(tiers.get('medium', 0)):,}",
        f"{int(tiers.get('low', 0)):,}",
    )
    log.info(
        "risk_score: min=%.6f median=%.6f max=%.6f",
        prob.min(),
        float(np.median(prob)),
        prob.max(),
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
