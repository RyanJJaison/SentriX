"""Log train/validation F1 per epoch to diagnose overfitting vs temporal shift.

The test-set gap observed in the ablation (train F1 ~0.98 against test F1 ~0.70)
has two candidate explanations, and they call for different fixes:

* **Overfitting during training** -- validation F1 would plateau or decline
  while train F1 keeps climbing.
* **Temporal shift to the test window** -- validation F1 would track train F1
  reasonably closely, since validation is drawn from the same era as training,
  leaving the drop to the later distribution of steps 35-49.

Validation is carved from the *training* window only (time steps
``TIME_STEP_VAL_START``-34), so the real test split stays untouched. Model
selection is deliberately left alone here: this module only records curves.

Run with::

    python -m src.curves                 # both configurations at seed 42
    python -m src.curves --seed 1337
"""

from __future__ import annotations

import argparse
import csv
import logging
import sys

import numpy as np
import torch
import torch.nn.functional as F

from src.config import (
    DATA_PROCESSED,
    LABEL_ILLICIT,
    TIME_STEP_VAL_START,
)
from src.train import (
    EPOCHS,
    LEARNING_RATE,
    SEED,
    WEIGHT_DECAY,
    GraphSAGE,
    evaluate,
    load_data,
    standardize,
)

log = logging.getLogger("curves")

CURVES_CSV = DATA_PROCESSED / "curves.csv"


def split_masks(data, time_steps: np.ndarray):
    """Carve a validation mask out of the training window.

    Returns ``(inner_train_mask, val_mask)``. The union is exactly the original
    ``train_mask``, so no labeled node is lost and the test mask is untouched.
    """
    train_mask = data.train_mask
    is_late = torch.from_numpy(time_steps >= TIME_STEP_VAL_START)

    val_mask = train_mask & is_late
    inner_train_mask = train_mask & ~is_late

    assert not bool((inner_train_mask & val_mask).any()), "inner train and val overlap"
    assert int((inner_train_mask | val_mask).sum()) == int(train_mask.sum()), (
        "the split does not cover the original training set"
    )
    assert int(val_mask.sum()) > 0, "empty validation split"
    assert int((data.y[val_mask] == LABEL_ILLICIT).sum()) > 0, "no illicit node in validation"
    return inner_train_mask, val_mask


def run_curve(raw_only: bool, seed: int, epochs: int) -> list[dict]:
    """Train once, recording train and validation metrics at every epoch."""
    torch.manual_seed(seed)
    np.random.seed(seed)

    data, x, _ = load_data(raw_only)

    # `time_step` is not stored on the PyG Data object, so it is recovered from
    # the PPR parquet, which is keyed by node_index in the same order.
    import pandas as pd

    from src.config import PPR_SCORES_PARQUET

    scores = pd.read_parquet(PPR_SCORES_PARQUET, columns=["node_index", "time_step"])
    scores = scores.sort_values("node_index")
    time_steps = scores["time_step"].to_numpy()
    assert len(time_steps) == data.num_nodes

    inner_train, val = split_masks(data, time_steps)
    label = "raw" if raw_only else "enriched"
    log.info(
        "%s: inner-train=%s (steps 1-%d) val=%s (steps %d-34) test=%s",
        label,
        f"{int(inner_train.sum()):,}",
        TIME_STEP_VAL_START - 1,
        f"{int(val.sum()):,}",
        TIME_STEP_VAL_START,
        f"{int(data.test_mask.sum()):,}",
    )
    log.info(
        "%s: illicit in inner-train=%s, in val=%s",
        label,
        f"{int((data.y[inner_train] == LABEL_ILLICIT).sum()):,}",
        f"{int((data.y[val] == LABEL_ILLICIT).sum()):,}",
    )

    # Standardize on the inner training split only. Using the full original
    # training set would leak validation-era statistics into the features.
    x = standardize(x, inner_train)

    n_pos = int((data.y[inner_train] == LABEL_ILLICIT).sum())
    n_neg = int((data.y[inner_train] != LABEL_ILLICIT).sum())
    pos_weight = torch.tensor(n_neg / n_pos, dtype=torch.float32)
    target = (data.y == LABEL_ILLICIT).float()

    model = GraphSAGE(in_dim=x.shape[1])
    optimizer = torch.optim.Adam(
        model.parameters(), lr=LEARNING_RATE, weight_decay=WEIGHT_DECAY
    )

    history: list[dict] = []
    for epoch in range(1, epochs + 1):
        model.train()
        optimizer.zero_grad()
        logits = model(x, data.edge_index)
        loss = F.binary_cross_entropy_with_logits(
            logits[inner_train], target[inner_train], pos_weight=pos_weight
        )
        loss.backward()
        optimizer.step()

        train_metrics = evaluate(model, x, data.edge_index, data.y, inner_train)
        val_metrics = evaluate(model, x, data.edge_index, data.y, val)
        # The test split is recorded for the diagnosis only. It never influences
        # training or any selection decision here.
        test_metrics = evaluate(model, x, data.edge_index, data.y, data.test_mask)

        history.append(
            {
                "config": label,
                "seed": seed,
                "epoch": epoch,
                "loss": float(loss),
                "train_f1": train_metrics["f1"],
                "train_auc": train_metrics["auc"],
                "val_f1": val_metrics["f1"],
                "val_auc": val_metrics["auc"],
                "test_f1": test_metrics["f1"],
                "test_auc": test_metrics["auc"],
            }
        )

        if epoch % 10 == 0 or epoch == 1:
            log.info(
                "%-8s epoch %3d loss=%.4f | train F1=%.4f AUC=%.4f | "
                "val F1=%.4f AUC=%.4f | test F1=%.4f",
                label,
                epoch,
                float(loss),
                train_metrics["f1"],
                train_metrics["auc"],
                val_metrics["f1"],
                val_metrics["auc"],
                test_metrics["f1"],
            )

    return history


def summarize(history: list[dict]) -> None:
    """Report the shape of the curves, which is what distinguishes the two causes."""
    label = history[0]["config"]
    train = [h["train_f1"] for h in history]
    val = [h["val_f1"] for h in history]
    test = [h["test_f1"] for h in history]

    best_val = max(range(len(val)), key=lambda i: val[i])
    best_train = max(range(len(train)), key=lambda i: train[i])
    final = len(history) - 1

    log.info("--- %s ---", label)
    log.info(
        "peak val F1=%.4f at epoch %d (train F1 there=%.4f, test F1=%.4f)",
        val[best_val],
        history[best_val]["epoch"],
        train[best_val],
        test[best_val],
    )
    log.info(
        "peak train F1=%.4f at epoch %d (val F1 there=%.4f)",
        train[best_train],
        history[best_train]["epoch"],
        val[best_train],
    )
    log.info(
        "final epoch %d: train=%.4f val=%.4f test=%.4f",
        history[final]["epoch"],
        train[final],
        val[final],
        test[final],
    )
    log.info(
        "val F1 change from its peak to the final epoch: %+.4f",
        val[final] - val[best_val],
    )
    log.info(
        "train-val gap: %+.4f at peak val, %+.4f at final epoch",
        train[best_val] - val[best_val],
        train[final] - val[final],
    )
    log.info(
        "val-test gap at final epoch: %+.4f",
        val[final] - test[final],
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=SEED)
    parser.add_argument("--epochs", type=int, default=EPOCHS)
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )

    rows: list[dict] = []
    for raw_only in (True, False):
        try:
            history = run_curve(raw_only, args.seed, args.epochs)
        except FileNotFoundError as exc:
            log.error("%s", exc)
            return 1
        summarize(history)
        rows.extend(history)

    DATA_PROCESSED.mkdir(parents=True, exist_ok=True)
    with CURVES_CSV.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    log.info("Wrote %s (%d rows)", CURVES_CSV, len(rows))
    return 0


if __name__ == "__main__":
    sys.exit(main())
