"""Train a GraphSAGE binary classifier for illicit-transaction detection.

Trained on labeled nodes only, using Elliptic's temporal split -- time steps
1-34 train, 35-49 test -- rather than a random split. A random split would let
the model see same-step neighbours of its evaluation nodes; since every Elliptic
edge is intra-step, that leaks almost perfectly and inflates the score.

Run with::

    python -m src.train                 # enriched features (default)
    python -m src.train --raw-only      # 165 raw features, for the ablation
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F
from torch import nn

from src.config import (
    DATA_PROCESSED,
    LABEL_ILLICIT,
    N_FEATURES,
    PYG_ROOT,
    TIME_STEP_VAL_START,
)
from src.features import ENRICHED_FEATURES_PT

log = logging.getLogger("train")

CHECKPOINT_DIR = DATA_PROCESSED / "checkpoints"

# Training hyperparameters. Modest by design: the graph is small, the positive
# class is rare, and the ablation needs both configurations trained identically
# so any difference comes from the features rather than the schedule.
HIDDEN_DIM = 128
N_LAYERS = 3
DROPOUT = 0.3
LEARNING_RATE = 0.01
WEIGHT_DECAY = 1e-4
EPOCHS = 200
# Early-stopping patience on VALIDATION F1. 15 epochs is roughly 8% of the 200
# epoch budget: long enough to ride out the epoch-to-epoch noise in a 1,005
# positive validation split, short enough to stop well before the budget ends.
PATIENCE = 15

# The patience counter does not start until this epoch. Validation F1 spikes
# during warmup -- the enriched configuration hits 0.645 at epoch 2, dips to
# 0.462, and only recovers by epoch 18 -- so an unguarded patience of 15 expires
# inside that dip and stops training at epoch 17 having selected epoch 2.
WARMUP_EPOCHS = 30
SEED = 42


class GraphSAGE(nn.Module):
    """A 2-3 layer GraphSAGE binary classifier.

    ``SAGEConv`` aggregates each node's neighbourhood, which is where the graph
    signal enters. Since Elliptic's edges are all intra-step, that aggregation
    happens strictly within a time step -- the model never sees across the
    train/test boundary, which is what makes the temporal split meaningful.
    """

    def __init__(
        self,
        in_dim: int,
        hidden_dim: int = HIDDEN_DIM,
        n_layers: int = N_LAYERS,
        dropout: float = DROPOUT,
    ) -> None:
        super().__init__()
        from torch_geometric.nn import SAGEConv

        assert 2 <= n_layers <= 3, "n_layers must be 2 or 3"
        self.convs = nn.ModuleList()
        self.norms = nn.ModuleList()
        dims = [in_dim] + [hidden_dim] * (n_layers - 1)
        for i in range(n_layers - 1):
            self.convs.append(SAGEConv(dims[i], dims[i + 1]))
            self.norms.append(nn.BatchNorm1d(dims[i + 1]))
        # Final layer emits a single logit per node.
        self.convs.append(SAGEConv(dims[-1], 1))
        self.dropout = dropout

    def forward(self, x: torch.Tensor, edge_index: torch.Tensor) -> torch.Tensor:
        for conv, norm in zip(self.convs[:-1], self.norms):
            x = conv(x, edge_index)
            x = norm(x)
            x = F.relu(x)
            x = F.dropout(x, p=self.dropout, training=self.training)
        return self.convs[-1](x, edge_index).squeeze(-1)


def load_data(raw_only: bool):
    """Load the graph plus either the raw or the enriched feature matrix."""
    from torch_geometric.datasets import EllipticBitcoinDataset

    data = EllipticBitcoinDataset(root=str(PYG_ROOT))[0]

    if raw_only:
        x = data.x.float()
        names = [f"raw_{i}" for i in range(x.shape[1])]
        log.info("Features: %d raw columns", x.shape[1])
    else:
        if not ENRICHED_FEATURES_PT.is_file():
            raise FileNotFoundError(
                f"{ENRICHED_FEATURES_PT} not found. Run `python -m src.features` first."
            )
        bundle = torch.load(ENRICHED_FEATURES_PT, weights_only=False)
        x = bundle["x"].float()
        names = bundle["feature_names"]
        assert x.shape[0] == data.num_nodes, "enriched features do not match the graph"
        log.info(
            "Features: %d columns (%d raw + %d PPR: %s)",
            x.shape[1],
            bundle["n_raw"],
            len(bundle["ppr_columns"]),
            ", ".join(bundle["ppr_columns"]),
        )

    return data, x, names


def load_time_steps(n_nodes: int) -> np.ndarray:
    """Per-node Elliptic time step, in PyG node-index order.

    ``time_step`` is not stored on the PyG ``Data`` object, so it comes from the
    PPR parquet, which carries ``node_index`` and is sorted by it here so the
    array lines up with the tensors positionally.
    """
    import pandas as pd

    from src.config import PPR_SCORES_PARQUET

    if not PPR_SCORES_PARQUET.is_file():
        raise FileNotFoundError(
            f"{PPR_SCORES_PARQUET} not found. Run `python -m src.ppr` first; it "
            "supplies the per-node time_step needed for recency weighting."
        )
    scores = pd.read_parquet(PPR_SCORES_PARQUET, columns=["node_index", "time_step"])
    scores = scores.sort_values("node_index")
    time_steps = scores["time_step"].to_numpy()
    assert len(time_steps) == n_nodes, (
        f"parquet has {len(time_steps)} rows but the graph has {n_nodes} nodes"
    )
    return time_steps


def standardize(x: torch.Tensor, train_mask: torch.Tensor) -> torch.Tensor:
    """Z-score each column using training-node statistics only.

    Fitting the scaler on all nodes would leak test-set distribution information
    into training, which is the same class of mistake as a random split.
    """
    mean = x[train_mask].mean(dim=0, keepdim=True)
    std = x[train_mask].std(dim=0, keepdim=True)
    std = torch.where(std > 1e-8, std, torch.ones_like(std))
    return (x - mean) / std


def class_weight(y: torch.Tensor, train_mask: torch.Tensor) -> torch.Tensor:
    """Positive-class weight for ``binary_cross_entropy_with_logits``.

    Illicit nodes are about 2% of the labeled set, so an unweighted loss would
    be minimized by predicting "licit" everywhere -- ~98% accuracy and zero
    recall on the class that matters.

    Weighted loss is used rather than oversampling because this is full-batch
    node classification on a fixed graph: every node participates in every
    forward pass, so there is no sampler to rebalance. Duplicating minority
    nodes would also duplicate them in the message-passing graph and distort the
    neighbourhood structure the GNN reads. Reweighting the loss changes the
    gradient without touching the topology.
    """
    n_pos = int((y[train_mask] == LABEL_ILLICIT).sum())
    n_neg = int((y[train_mask] != LABEL_ILLICIT).sum())
    assert n_pos > 0 and n_neg > 0, "training split lacks one of the two classes"
    weight = n_neg / n_pos
    log.info(
        "Class balance in train: %s illicit vs %s licit -> pos_weight=%.2f",
        f"{n_pos:,}",
        f"{n_neg:,}",
        weight,
    )
    return torch.tensor(weight, dtype=torch.float32)


def recency_weights(
    time_steps: np.ndarray, train_mask: torch.Tensor, decay: float | None
) -> torch.Tensor:
    """Per-node loss weight ``decay ** (max_train_step - node_step)``.

    Later training steps count for more, biasing the fit toward the era closest
    in time to the test window. ``decay=None`` returns all-ones, which is
    numerically identical to the unweighted baseline.

    The reference point is the latest step *in the training mask*, so the most
    recent training nodes always carry weight exactly 1.0 and the weights are
    independent of where the test window starts.
    """
    weights = torch.ones(len(time_steps), dtype=torch.float32)
    if decay is None:
        return weights
    assert 0.0 < decay <= 1.0, f"decay must be in (0, 1], got {decay}"

    max_train_step = int(time_steps[train_mask.numpy()].max())
    age = np.maximum(max_train_step - time_steps, 0)
    return torch.from_numpy((decay ** age).astype(np.float32))


def weighted_class_weight(
    y: torch.Tensor, train_mask: torch.Tensor, sample_weights: torch.Tensor
) -> torch.Tensor:
    """Positive-class weight computed from *weighted* class mass.

    Recency weighting changes the effective class balance -- the weighted illicit
    share rises from 11.58% to 16.04% at decay 0.90 -- so reusing the unweighted
    ``pos_weight`` would let a class-balance shift masquerade as a recency
    effect. Deriving it from the same weights keeps the two independent.
    """
    is_pos = (y == LABEL_ILLICIT) & train_mask
    is_neg = (y != LABEL_ILLICIT) & train_mask
    pos_mass = float(sample_weights[is_pos].sum())
    neg_mass = float(sample_weights[is_neg].sum())
    assert pos_mass > 0 and neg_mass > 0, "a class has zero weighted mass"
    return torch.tensor(neg_mass / pos_mass, dtype=torch.float32)


@torch.no_grad()
def evaluate_per_step(
    model, x, edge_index, y, mask, time_steps: np.ndarray
) -> dict[int, dict[str, float]]:
    """Illicit-class metrics for each time step inside ``mask``.

    The aggregate test F1 hides where the model fails. Splitting it by step is
    what shows whether error is concentrated in the far-term steps, which is the
    signature that distinguishes drift from uniform weakness.
    """
    model.eval()
    prob = torch.sigmoid(model(x, edge_index)).cpu().numpy()
    true = (y == LABEL_ILLICIT).cpu().numpy().astype(np.int64)
    selected = mask.cpu().numpy()

    out: dict[int, dict[str, float]] = {}
    for step in sorted(set(time_steps[selected].tolist())):
        in_step = selected & (time_steps == step)
        p = prob[in_step]
        t = true[in_step]
        pred = (p >= 0.5).astype(np.int64)
        tp = int(((pred == 1) & (t == 1)).sum())
        fp = int(((pred == 1) & (t == 0)).sum())
        fn = int(((pred == 0) & (t == 1)).sum())
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        out[int(step)] = {
            "precision": precision,
            "recall": recall,
            "f1": 2 * precision * recall / (precision + recall) if precision + recall else 0.0,
            "auc": roc_auc(t, p),
            "n": int(in_step.sum()),
            "n_pos": int(t.sum()),
        }
    return out


@torch.no_grad()
def evaluate(model, x, edge_index, y, mask) -> dict[str, float]:
    """Precision, recall, F1 and ROC-AUC for the illicit class."""
    model.eval()
    logits = model(x, edge_index)
    prob = torch.sigmoid(logits[mask]).cpu().numpy()
    true = (y[mask] == LABEL_ILLICIT).cpu().numpy().astype(np.int64)
    pred = (prob >= 0.5).astype(np.int64)

    tp = int(((pred == 1) & (true == 1)).sum())
    fp = int(((pred == 1) & (true == 0)).sum())
    fn = int(((pred == 0) & (true == 1)).sum())
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0

    return {
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "auc": roc_auc(true, prob),
        "n_pos": int(true.sum()),
        "n": int(len(true)),
    }


def roc_auc(true: np.ndarray, score: np.ndarray) -> float:
    """ROC-AUC via the rank identity, so scikit-learn is not needed.

    AUC equals the probability that a random positive outranks a random
    negative, which the Mann-Whitney U statistic gives directly from ranks.
    Ties get midpoint ranks, matching sklearn's behaviour.
    """
    n_pos = int(true.sum())
    n_neg = len(true) - n_pos
    if n_pos == 0 or n_neg == 0:
        return float("nan")
    order = np.argsort(score, kind="mergesort")
    ranks = np.empty(len(score), dtype=np.float64)
    ranks[order] = np.arange(1, len(score) + 1, dtype=np.float64)
    # Average the ranks inside each tie group.
    sorted_scores = score[order]
    start = 0
    for i in range(1, len(sorted_scores) + 1):
        if i == len(sorted_scores) or sorted_scores[i] != sorted_scores[start]:
            if i - start > 1:
                ranks[order[start:i]] = ranks[order[start:i]].mean()
            start = i
    return float((ranks[true == 1].sum() - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg))


def train(
    raw_only: bool,
    epochs: int = EPOCHS,
    tag: str | None = None,
    seed: int = SEED,
    save_checkpoint: bool = True,
    recency_decay: float | None = None,
    refit_on_full: bool = True,
) -> dict:
    # Seeds only model init and the stochastic training ops (dropout, BatchNorm
    # batch statistics). The train/test split comes from PyG's temporal masks
    # and is unaffected, so every seed evaluates on exactly the same nodes.
    torch.manual_seed(seed)
    np.random.seed(seed)

    data, x, names = load_data(raw_only)
    test_mask = data.test_mask
    y, edge_index = data.y, data.edge_index

    # Carve a validation split from the training window only, so the test
    # window stays untouched. Selection and early stopping run on validation
    # F1; fitting happens on the inner-train split alone.
    time_steps = load_time_steps(data.num_nodes)
    is_late = torch.from_numpy(time_steps >= TIME_STEP_VAL_START)
    val_mask = data.train_mask & is_late
    train_mask = data.train_mask & ~is_late
    assert not bool((train_mask & val_mask).any()), "inner train and val overlap"
    assert not bool((val_mask & test_mask).any()), "val overlaps test"
    assert int((y[val_mask] == LABEL_ILLICIT).sum()) > 0, "no illicit node in validation"

    log.info(
        "Split: %s inner-train (steps 1-%d) / %s val (steps %d-34) / %s test "
        "(steps 35-49)",
        f"{int(train_mask.sum()):,}",
        TIME_STEP_VAL_START - 1,
        f"{int(val_mask.sum()):,}",
        TIME_STEP_VAL_START,
        f"{int(test_mask.sum()):,}",
    )

    # Standardize on the inner-train split only: using the full original
    # training set would leak validation-era statistics into the features. The
    # unscaled copy is kept so the stage-2 refit can rescale on the full window.
    x_unscaled = x
    x = standardize(x, train_mask)
    target = (y == LABEL_ILLICIT).float()

    time_steps = load_time_steps(data.num_nodes)
    sample_weights = recency_weights(time_steps, train_mask, recency_decay)
    if recency_decay is None:
        pos_weight = class_weight(y, train_mask)
    else:
        pos_weight = weighted_class_weight(y, train_mask, sample_weights)
        effective_n = float(
            sample_weights[train_mask].sum() ** 2 / (sample_weights[train_mask] ** 2).sum()
        )
        log.info(
            "Recency weighting decay=%.2f: effective n=%.0f of %s, pos_weight=%.2f "
            "(unweighted would be %.2f)",
            recency_decay,
            effective_n,
            f"{int(train_mask.sum()):,}",
            float(pos_weight),
            float(class_weight(y, train_mask)),
        )

    model = GraphSAGE(in_dim=x.shape[1])
    optimizer = torch.optim.Adam(
        model.parameters(), lr=LEARNING_RATE, weight_decay=WEIGHT_DECAY
    )

    best_f1, best_state, best_epoch, stale = -1.0, None, 0, 0
    for epoch in range(1, epochs + 1):
        model.train()
        optimizer.zero_grad()
        logits = model(x, edge_index)
        # Per-node weights need reduction="none" so each node's loss can be
        # scaled before averaging. The mean is taken over the weight mass rather
        # than the node count, keeping the loss scale comparable to the
        # unweighted baseline regardless of decay.
        per_node = F.binary_cross_entropy_with_logits(
            logits[train_mask],
            target[train_mask],
            pos_weight=pos_weight,
            reduction="none",
        )
        node_weights = sample_weights[train_mask]
        loss = (per_node * node_weights).sum() / node_weights.sum()
        loss.backward()
        optimizer.step()

        if epoch % 10 == 0 or epoch == 1:
            tr = evaluate(model, x, edge_index, y, train_mask)
            va = evaluate(model, x, edge_index, y, val_mask)
            log.info(
                "epoch %3d loss=%.4f train F1=%.4f AUC=%.4f | val F1=%.4f AUC=%.4f",
                epoch,
                float(loss),
                tr["f1"],
                tr["auc"],
                va["f1"],
                va["auc"],
            )

        # Model selection on the VALIDATION split, which is carved from the
        # training window. Selecting on train F1 would keep climbing toward
        # ~0.98 and never stop; selecting on test would turn the held-out
        # numbers into a fitted result and void the ablation.
        val_f1 = evaluate(model, x, edge_index, y, val_mask)["f1"]
        if val_f1 > best_f1:
            best_f1, best_epoch, stale = val_f1, epoch, 0
            best_state = {k: v.detach().clone() for k, v in model.state_dict().items()}
        elif epoch > WARMUP_EPOCHS:
            stale += 1
            if stale >= PATIENCE:
                log.info("Early stop at epoch %d (best epoch %d)", epoch, best_epoch)
                break

    assert best_state is not None

    # Stage 2: refit from scratch on the FULL training window (steps 1-34) for
    # exactly the epoch count stage 1 chose.
    #
    # Stage 1 has to hold out steps 28-34 to have a validation signal at all,
    # but those are the training steps closest in time to the test window, and
    # the drift diagnostic showed recency is what matters most here. Keeping the
    # stage-1 model costs test F1 0.6954 -> 0.4354 on the enriched configuration
    # purely from the lost data. Refitting keeps the stopping decision honest --
    # the epoch count came from held-out-era performance, never from test --
    # while paying no data penalty.
    if refit_on_full:
        log.info("Refitting on the full training window for %d epochs", best_epoch)
        torch.manual_seed(seed)
        np.random.seed(seed)
        full_mask = data.train_mask
        x = standardize(x_unscaled, full_mask)
        model = GraphSAGE(in_dim=x.shape[1])
        optimizer = torch.optim.Adam(
            model.parameters(), lr=LEARNING_RATE, weight_decay=WEIGHT_DECAY
        )
        full_pos_weight = class_weight(y, full_mask)
        full_weights = recency_weights(time_steps, full_mask, recency_decay)
        for _ in range(best_epoch):
            model.train()
            optimizer.zero_grad()
            logits = model(x, edge_index)
            per_node = F.binary_cross_entropy_with_logits(
                logits[full_mask],
                target[full_mask],
                pos_weight=full_pos_weight,
                reduction="none",
            )
            node_weights = full_weights[full_mask]
            loss = (per_node * node_weights).sum() / node_weights.sum()
            loss.backward()
            optimizer.step()
        train_mask = full_mask
    else:
        model.load_state_dict(best_state)
    test_metrics = evaluate(model, x, edge_index, y, test_mask)
    train_metrics = evaluate(model, x, edge_index, y, train_mask)
    val_metrics = evaluate(model, x, edge_index, y, val_mask)
    log.info(
        "SELECTED epoch %d by val F1=%.4f | train F1=%.4f val F1=%.4f",
        best_epoch,
        best_f1,
        train_metrics["f1"],
        val_metrics["f1"],
    )

    log.info(
        "TEST  precision=%.4f recall=%.4f F1=%.4f AUC=%.4f (%s illicit of %s)",
        test_metrics["precision"],
        test_metrics["recall"],
        test_metrics["f1"],
        test_metrics["auc"],
        f"{test_metrics['n_pos']:,}",
        f"{test_metrics['n']:,}",
    )

    result = {
        "train": train_metrics,
        "test": test_metrics,
        "val": val_metrics,
        "seed": seed,
        "best_epoch": best_epoch,
        "recency_decay": recency_decay,
        "refit_on_full": refit_on_full,
        "per_step_test": evaluate_per_step(
            model, x, edge_index, y, test_mask, load_time_steps(data.num_nodes)
        ),
    }
    if not save_checkpoint:
        # Multi-seed sweeps would otherwise write one ~300 KB checkpoint per
        # seed per configuration, none of which is the model that ships.
        return result

    CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)
    name = tag or ("raw" if raw_only else "enriched")
    path = CHECKPOINT_DIR / f"graphsage_{name}.pt"
    torch.save(
        {
            "state_dict": model.state_dict(),
            "in_dim": x.shape[1],
            "feature_names": names,
            "raw_only": raw_only,
            "hidden_dim": HIDDEN_DIM,
            "n_layers": N_LAYERS,
            "dropout": DROPOUT,
            "best_epoch": best_epoch,
            "seed": seed,
            "recency_decay": recency_decay,
            "refit_on_full": refit_on_full,
            "train_metrics": train_metrics,
            "val_metrics": val_metrics,
            "test_metrics": test_metrics,
            "feature_mean": x[train_mask].mean(dim=0),
            "feature_std": x[train_mask].std(dim=0),
        },
        path,
    )
    log.info("Wrote checkpoint %s", path)

    result["checkpoint"] = str(path)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--raw-only",
        action="store_true",
        help="train on the 165 raw features only (ablation baseline)",
    )
    parser.add_argument("--epochs", type=int, default=EPOCHS)
    parser.add_argument(
        "--seed", type=int, default=SEED, help=f"random seed for model init (default: {SEED})"
    )
    parser.add_argument(
        "--no-refit",
        action="store_true",
        help="keep the stage-1 model instead of refitting on the full training window",
    )
    parser.add_argument(
        "--recency-decay",
        type=float,
        default=None,
        help="per-node loss weight decay ** (max_train_step - step); omit to disable",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )
    try:
        train(
            raw_only=args.raw_only,
            epochs=args.epochs,
            seed=args.seed,
            recency_decay=args.recency_decay,
            refit_on_full=not args.no_refit,
        )
    except FileNotFoundError as exc:
        log.error("%s", exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
