"""Ablation: do the PPR graph features improve the GNN over raw features alone?

Trains both configurations -- 165 raw Elliptic features, and those plus the four
PPR columns -- across several seeds and reports mean +/- standard deviation for
each illicit-class metric on the temporal test split.

Multiple seeds matter because a single run cannot separate a real feature effect
from initialization luck. The train/test split is fixed by Elliptic's time steps
and is identical for every seed, so the only thing varying is model
initialization and the stochastic training ops (dropout, BatchNorm statistics).

Run with::

    python -m src.ablation                       # default 3 seeds
    python -m src.ablation --seeds 42 1337 2024 7
"""

from __future__ import annotations

import argparse
import logging
import statistics
import sys

from src.config import DATA_PROCESSED
from src.features import PPR_FEATURE_COLUMNS
from src.train import train

log = logging.getLogger("ablation")

ABLATION_MD = DATA_PROCESSED / "ablation.md"

DEFAULT_SEEDS = (42, 1337, 2024)
METRICS = ("precision", "recall", "f1", "auc")

CONFIGS = (
    ("raw", True, "165 raw"),
    ("enriched", False, "enriched (169)"),
)


def summarize(runs: list[dict], split: str, metric: str) -> tuple[float, float]:
    """Mean and sample standard deviation of one metric across seeds."""
    values = [run[split][metric] for run in runs]
    mean = statistics.fmean(values)
    # Sample (n-1) standard deviation; undefined for a single run.
    std = statistics.stdev(values) if len(values) > 1 else 0.0
    return mean, std


def format_table(results: dict[str, list[dict]], seeds: tuple[int, ...]) -> str:
    """Render the multi-seed comparison as markdown."""
    n = len(seeds)
    lines = [
        "# Ablation: raw features vs PPR-enriched features",
        "",
        "GraphSAGE binary classifier, illicit class, Elliptic temporal split.",
        "",
        "Two-stage protocol. Stage 1 fits on inner-train (time steps 1-27) and",
        "chooses the epoch count by validation F1 (steps 28-34, patience 15 with a",
        "30-epoch warmup floor). Stage 2 refits from scratch on the full training",
        "window (steps 1-34) for exactly that many epochs. Test (steps 35-49) is",
        "never read for any decision in either stage. Identical architecture and",
        "schedule in both configurations; the only difference is the feature matrix.",
        "",
        f"Seeds: {', '.join(str(s) for s in seeds)} ({n} runs per configuration).",
        "The split is fixed by the time steps and identical across seeds, so only",
        "model initialization and the stochastic training ops vary.",
        "",
        f"Added columns: `{'`, `'.join(PPR_FEATURE_COLUMNS)}`",
        "",
        "## Test-set metrics (illicit class), mean +/- sd",
        "",
        "| Metric | (a) 165 raw | (b) enriched (169) | Delta of means |",
        "| --- | --- | --- | --- |",
    ]

    for metric in METRICS:
        a_mean, a_std = summarize(results["raw"], "test", metric)
        b_mean, b_std = summarize(results["enriched"], "test", metric)
        delta = b_mean - a_mean
        # Flag a delta that does not clear the combined spread, since that is
        # the case where the seeds do not actually separate the two configs.
        marker = "" if abs(delta) > a_std + b_std else " (within spread)"
        lines.append(
            f"| {metric.upper()} | {a_mean:.4f} +/- {a_std:.4f} | "
            f"{b_mean:.4f} +/- {b_std:.4f} | {delta:+.4f}{marker} |"
        )

    lines += [
        "",
        "## Train-set metrics (illicit class), mean +/- sd",
        "",
        "| Metric | (a) 165 raw | (b) enriched (169) | Delta of means |",
        "| --- | --- | --- | --- |",
    ]
    for metric in METRICS:
        a_mean, a_std = summarize(results["raw"], "train", metric)
        b_mean, b_std = summarize(results["enriched"], "train", metric)
        lines.append(
            f"| {metric.upper()} | {a_mean:.4f} +/- {a_std:.4f} | "
            f"{b_mean:.4f} +/- {b_std:.4f} | {b_mean - a_mean:+.4f} |"
        )

    lines += ["", "## Per-seed test F1 and AUC", "", "| Seed | raw F1 | enriched F1 | raw AUC | enriched AUC |", "| --- | --- | --- | --- | --- |"]
    for i, seed in enumerate(seeds):
        r, e = results["raw"][i], results["enriched"][i]
        lines.append(
            f"| {seed} | {r['test']['f1']:.4f} | {e['test']['f1']:.4f} | "
            f"{r['test']['auc']:.4f} | {e['test']['auc']:.4f} |"
        )

    first = results["raw"][0]["test"]
    lines += [
        "",
        f"Test split: {first['n_pos']:,} illicit of {first['n']:,} labeled nodes "
        f"({100 * first['n_pos'] / first['n']:.2f}% positive).",
        "",
        "## Reading these numbers",
        "",
        "The PPR columns are sparse on held-out data: only 13.0% of illicit test",
        "nodes have a nonzero `ppr_fwd_score` and 18.7% a nonzero `ppr_rev_score`,",
        "because every Elliptic edge stays inside one time step and most nodes have",
        "no illicit node in their own step's reachable set. Any gain is therefore",
        "concentrated in that minority of nodes rather than spread across all of them.",
        "",
        "Both configurations choose their epoch count on validation F1, never on",
        "test, so the test columns are genuine held-out measurements.",
        "",
        "A delta marked *(within spread)* does not exceed the sum of the two",
        "standard deviations, meaning these seeds do not separate the configurations",
        "on that metric.",
    ]
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--seeds",
        type=int,
        nargs="+",
        default=list(DEFAULT_SEEDS),
        help=f"seeds to average over (default: {' '.join(map(str, DEFAULT_SEEDS))})",
    )
    args = parser.parse_args()
    seeds = tuple(args.seeds)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )

    results: dict[str, list[dict]] = {name: [] for name, _, _ in CONFIGS}
    for name, raw_only, label in CONFIGS:
        for seed in seeds:
            log.info("=== %s, seed %d ===", label, seed)
            try:
                # Only the first seed writes a checkpoint, so the shipped model
                # stays reproducible at the documented default seed.
                run = train(
                    raw_only=raw_only,
                    tag=name,
                    seed=seed,
                    save_checkpoint=(seed == seeds[0]),
                )
            except FileNotFoundError as exc:
                log.error("%s", exc)
                return 1
            results[name].append(run)
            log.info(
                "%s seed=%d test F1=%.4f AUC=%.4f",
                label,
                seed,
                run["test"]["f1"],
                run["test"]["auc"],
            )

    table = format_table(results, seeds)
    DATA_PROCESSED.mkdir(parents=True, exist_ok=True)
    ABLATION_MD.write_text(table)
    log.info("Wrote %s", ABLATION_MD)
    print()
    print(table)
    return 0


if __name__ == "__main__":
    sys.exit(main())
