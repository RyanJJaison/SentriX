"""Join the PPR graph features onto Elliptic's raw node features.

The output is a single dense feature matrix in PyG node-index order, ready to
hand to a GNN. The join is by ``txId`` rather than by position, because the
parquet is keyed by transaction id while the model consumes tensors indexed by
PyG's node index -- relying on row order to line those up is exactly the class
of bug ``validate_mapping`` exists to catch.

Run with::

    python -m src.features
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import torch

from src.config import (
    DATA_PROCESSED,
    DATA_RAW,
    N_FEATURES,
    N_NODES,
    PPR_SCORES_PARQUET,
    RAW_FEATURES,
)

log = logging.getLogger("features")

ENRICHED_FEATURES_PT = DATA_PROCESSED / "features_enriched.pt"

# The PPR columns to append, in a fixed order so the tensor layout is stable
# across runs and the ablation can name each column by index.
PPR_FEATURE_COLUMNS = (
    "ppr_fwd_score",
    "ppr_fwd_percentile",
    "ppr_rev_score",
    "ppr_rev_percentile",
)


def load_raw_features(raw_dir: Path = DATA_RAW) -> pd.DataFrame:
    """Read all 165 raw features plus ``txId`` and ``time_step``.

    Unlike the PPR pipeline, which skips the feature columns, this needs the full
    ~690 MB file. Columns 0 and 1 are ``txId`` and ``time_step``; 2 onward are
    the features.
    """
    log.info("Reading raw features from %s (this reads the full ~690 MB file)", raw_dir)
    feat_df = pd.read_csv(raw_dir / RAW_FEATURES, header=None)
    feat_df = feat_df.rename(columns={0: "txId", 1: "time_step"})
    assert len(feat_df) == N_NODES, f"expected {N_NODES} rows, got {len(feat_df)}"
    n_feat = feat_df.shape[1] - 2
    assert n_feat == N_FEATURES, f"expected {N_FEATURES} features, got {n_feat}"
    log.info("Raw features: %s nodes x %d features", f"{len(feat_df):,}", n_feat)
    return feat_df


def load_ppr_scores(path: Path = PPR_SCORES_PARQUET) -> pd.DataFrame:
    if not path.is_file():
        raise FileNotFoundError(
            f"{path} not found. Run `python -m src.ppr` first to compute the PPR features."
        )
    scores = pd.read_parquet(path)
    missing = [c for c in PPR_FEATURE_COLUMNS if c not in scores.columns]
    assert not missing, f"PPR parquet is missing columns: {missing}"
    log.info("PPR scores: %s rows, columns %s", f"{len(scores):,}", list(scores.columns))
    return scores


def build_enriched_features(
    feat_df: pd.DataFrame, scores: pd.DataFrame
) -> tuple[torch.Tensor, list[str]]:
    """Return the enriched feature tensor in PyG node-index order, plus names.

    PyG assigns node indices by the row order of the features CSV, so that order
    is the target layout. The PPR columns are joined onto it by ``txId``.
    """
    # PyG's node index == features-CSV row order, so this frame is already in
    # the target order and its position is the node index.
    tx_ids = feat_df["txId"].to_numpy(np.int64)

    indexed = scores.set_index("txId")
    assert indexed.index.is_unique, "duplicate txId in the PPR parquet"
    joined = indexed.reindex(tx_ids)

    # A missing row here would mean the parquet does not cover every node. That
    # must fail rather than be filled, because a zero fill is indistinguishable
    # from a real zero score (an unreachable node) and would silently corrupt
    # the feature.
    unmatched = int(joined[list(PPR_FEATURE_COLUMNS)].isna().any(axis=1).sum())
    assert unmatched == 0, (
        f"{unmatched} node(s) have no PPR row; the parquet does not cover the graph"
    )

    raw = feat_df.drop(columns=["txId", "time_step"]).to_numpy(np.float32)
    ppr = joined[list(PPR_FEATURE_COLUMNS)].to_numpy(np.float32)
    enriched = np.concatenate([raw, ppr], axis=1)

    assert enriched.shape == (N_NODES, N_FEATURES + len(PPR_FEATURE_COLUMNS))
    assert not np.isnan(enriched).any(), "NaN in the enriched feature matrix"
    assert np.isfinite(enriched).all(), "non-finite value in the enriched feature matrix"

    names = [f"raw_{i}" for i in range(raw.shape[1])] + list(PPR_FEATURE_COLUMNS)
    return torch.from_numpy(enriched), names


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )

    try:
        scores = load_ppr_scores()
    except FileNotFoundError as exc:
        log.error("%s", exc)
        return 1

    feat_df = load_raw_features()
    x, names = build_enriched_features(feat_df, scores)

    DATA_PROCESSED.mkdir(parents=True, exist_ok=True)
    torch.save(
        {
            "x": x,
            "feature_names": names,
            "n_raw": N_FEATURES,
            "ppr_columns": list(PPR_FEATURE_COLUMNS),
            "tx_ids": torch.from_numpy(feat_df["txId"].to_numpy(np.int64).copy()),
        },
        ENRICHED_FEATURES_PT,
    )

    log.info(
        "Enriched features: %s nodes x %d columns (%d raw + %d PPR)",
        f"{x.shape[0]:,}",
        x.shape[1],
        N_FEATURES,
        len(PPR_FEATURE_COLUMNS),
    )
    log.info("No NaN introduced by the join (checked all %d PPR columns)", len(PPR_FEATURE_COLUMNS))
    for i, col in enumerate(PPR_FEATURE_COLUMNS):
        values = x[:, N_FEATURES + i]
        n_zero = int((values == 0.0).sum())
        log.info(
            "    %-20s min=%.6f max=%.6f zeros=%s (%.2f%%)",
            col,
            float(values.min()),
            float(values.max()),
            f"{n_zero:,}",
            100 * n_zero / len(values),
        )
    log.info("Wrote %s", ENRICHED_FEATURES_PT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
