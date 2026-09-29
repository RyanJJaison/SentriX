"""Fuse GNN graph risk with traffic-anomaly signal into a combined risk score.

Reads `output/scores.jsonl` (one GNN record per line) and writes
`output/fused_scores.jsonl` with the same schema plus a `signals_used` field.

The central design rule: **a missing signal is not a zero signal.** An address
with no traffic data keeps its GNN score at full weight rather than being
penalized by multiplying an absent traffic score by 0.3. Zero-filling would
push every uncovered address downward by up to 30% of its risk, and since
coverage is expected to be sparse that would misrank the majority of the book.

Run with::

    python -m src.fusion
    python -m src.fusion --coverage 0.5 --seed 7
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import random
import statistics
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from src.config import PROJECT_ROOT
from src.export import SCORES_JSONL, risk_tier

log = logging.getLogger("fusion")

FUSED_SCORES_JSONL = PROJECT_ROOT / "output" / "fused_scores.jsonl"

FUSION_VERSION = "fusion-v0.1"

# Fusion weights, used only when both signals are present.
WEIGHT_GNN = 0.7
WEIGHT_TRAFFIC = 0.3

# Fraction of addresses the stub leaves without traffic data. Real coverage is
# expected to be sparse, so the default models that rather than assuming
# full coverage the pipeline will not have.
DEFAULT_MISSING_RATE = 0.7

CONFIDENCE_LEVELS = ("low", "medium", "high")


# --------------------------------------------------------------------------- #
# Traffic signal source — THE ONLY STUB
#
# Replace the body of `get_traffic_signal` with a real lookup (a client call, a
# parquet join, a cache read) and nothing else in this module changes. It must
# keep the same contract:
#
#   returns {"traffic_anomaly_score": float in [0, 1],
#            "confidence": "low" | "medium" | "high"}
#   or      None, meaning no traffic data for this address
#
# Returning None is a first-class outcome, not an error: the fusion path below
# treats it as "this signal does not exist for this address" and reweights.
# --------------------------------------------------------------------------- #


def get_traffic_signal(
    address_id: str, missing_rate: float = DEFAULT_MISSING_RATE, seed: int = 0
) -> dict | None:
    """Stubbed traffic-anomaly lookup for one address.

    The draw is derived from a hash of ``address_id`` rather than from a shared
    RNG, which makes it deterministic per address and independent of iteration
    order. A rerun therefore returns the same verdict for the same address, and
    the result does not change if records are processed in a different order or
    in parallel — properties a real lookup would also have, so the stub does not
    flatter the pipeline in ways the replacement would not.
    """
    digest = hashlib.sha256(f"{seed}:{address_id}".encode()).digest()
    rng = random.Random(digest)

    if rng.random() < missing_rate:
        return None

    return {
        "traffic_anomaly_score": round(rng.random(), 6),
        # Weighted toward lower confidence, which is the realistic shape for a
        # sparse behavioural signal.
        "confidence": rng.choices(CONFIDENCE_LEVELS, weights=(0.5, 0.35, 0.15))[0],
    }


# --------------------------------------------------------------------------- #
# Fusion
# --------------------------------------------------------------------------- #


def fuse(gnn_score: float, traffic: dict | None) -> tuple[float, list[dict], list[str]]:
    """Combine the available signals into a score, factors and signal list.

    Returns ``(risk_score, contributing_factors, signals_used)``.

    Weights in the returned factors are the *effective* weights — what was
    actually applied — so they always sum to 1.0 and the contributions always
    sum to ``risk_score``. With traffic present that is 0.7/0.3; with traffic
    absent the GNN factor carries weight 1.0 and no traffic factor is emitted at
    all. A consumer reading a weight of 0.7 can therefore trust that a traffic
    factor exists alongside it.
    """
    if traffic is None:
        risk = gnn_score
        factors = [
            {
                "name": "gnn_score",
                "value": round(gnn_score, 6),
                "weight": 1.0,
                "contribution": round(gnn_score, 6),
            }
        ]
        return risk, factors, ["gnn"]

    traffic_score = float(traffic["traffic_anomaly_score"])
    assert 0.0 <= traffic_score <= 1.0, f"traffic score out of range: {traffic_score}"

    gnn_contribution = WEIGHT_GNN * gnn_score
    traffic_contribution = WEIGHT_TRAFFIC * traffic_score
    risk = gnn_contribution + traffic_contribution

    factors = [
        {
            "name": "gnn_score",
            "value": round(gnn_score, 6),
            "weight": WEIGHT_GNN,
            "contribution": round(gnn_contribution, 6),
        },
        {
            "name": "traffic_anomaly",
            "value": round(traffic_score, 6),
            "weight": WEIGHT_TRAFFIC,
            "contribution": round(traffic_contribution, 6),
            "confidence": traffic["confidence"],
        },
    ]
    return risk, factors, ["gnn", "traffic"]


def read_gnn_score(record: dict) -> float:
    """Pull the GNN score out of an input record.

    ``risk_score`` on the input is the GNN probability, since the input is the
    pre-fusion export. It is cross-checked against the ``gnn_score`` factor so a
    schema change upstream surfaces here instead of silently fusing the wrong
    number.
    """
    score = float(record["risk_score"])
    factors = {f["name"]: f for f in record.get("contributing_factors", [])}
    gnn_factor = factors.get("gnn_score")
    assert gnn_factor is not None, (
        f"input record for {record.get('address_id')!r} has no gnn_score factor; "
        "is output/scores.jsonl the pre-fusion export?"
    )
    assert abs(float(gnn_factor["value"]) - score) < 1e-6, (
        f"input risk_score {score} disagrees with its gnn_score factor "
        f"{gnn_factor['value']} for {record.get('address_id')!r}"
    )
    assert 0.0 <= score <= 1.0, f"gnn score out of range: {score}"
    return score


def fuse_record(record: dict, scored_at: str, missing_rate: float, seed: int) -> dict:
    """Build one fused output record."""
    address_id = record["address_id"]
    gnn_score = read_gnn_score(record)
    traffic = get_traffic_signal(address_id, missing_rate=missing_rate, seed=seed)

    risk, factors, signals = fuse(gnn_score, traffic)

    # The contract downstream consumers rely on: the factor contributions
    # reconstruct the score exactly.
    total = sum(f["contribution"] for f in factors)
    assert abs(total - risk) < 1e-5, (
        f"contributions {total} do not sum to risk_score {risk} for {address_id!r}"
    )
    weight_total = sum(f["weight"] for f in factors)
    assert abs(weight_total - 1.0) < 1e-9, (
        f"effective weights sum to {weight_total}, not 1.0, for {address_id!r}"
    )

    return {
        "address_id": address_id,
        "risk_score": round(risk, 6),
        "risk_tier": risk_tier(risk),
        "signals_used": signals,
        "contributing_factors": factors,
        # Carried through unchanged from the GNN export.
        "graph_context": record["graph_context"],
        "model_version": record["model_version"],
        "fusion_version": FUSION_VERSION,
        "scored_at": scored_at,
    }


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        type=Path,
        default=SCORES_JSONL,
        help=f"GNN scores JSONL (default: {SCORES_JSONL})",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=FUSED_SCORES_JSONL,
        help=f"fused output JSONL (default: {FUSED_SCORES_JSONL})",
    )
    parser.add_argument(
        "--coverage",
        type=float,
        default=None,
        help="fraction of addresses WITH traffic data (default: "
        f"{1 - DEFAULT_MISSING_RATE:.2f}); stub only",
    )
    parser.add_argument(
        "--seed", type=int, default=0, help="stub traffic seed (default: 0)"
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )

    if not args.input.is_file():
        log.error(
            "%s not found. Run `python -m src.export` first to produce the GNN scores.",
            args.input,
        )
        return 1

    missing_rate = DEFAULT_MISSING_RATE
    if args.coverage is not None:
        assert 0.0 <= args.coverage <= 1.0, "coverage must be in [0, 1]"
        missing_rate = 1.0 - args.coverage

    scored_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    tiers: Counter[str] = Counter()
    signal_sets: Counter[str] = Counter()
    confidences: Counter[str] = Counter()
    n = 0
    fused_scores: list[float] = []
    gnn_scores: list[float] = []
    # Fused and input scores kept per signal group. The point of splitting them
    # is that any mean shift MUST be confined to the both-signal group: a
    # GNN-only address is passed through untouched, so movement there would mean
    # the missing signal is leaking into the formula.
    by_group: dict[str, dict[str, list[float]]] = {
        "gnn": {"fused": [], "gnn": []},
        "gnn+traffic": {"fused": [], "gnn": []},
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.input.open(encoding="utf-8") as src, args.output.open(
        "w", encoding="utf-8"
    ) as dst:
        for line in src:
            line = line.strip()
            if not line:
                continue
            record = fuse_record(json.loads(line), scored_at, missing_rate, args.seed)
            dst.write(json.dumps(record) + "\n")

            n += 1
            group = "+".join(record["signals_used"])
            tiers[record["risk_tier"]] += 1
            signal_sets[group] += 1
            fused_scores.append(record["risk_score"])
            by_group[group]["fused"].append(record["risk_score"])
            for factor in record["contributing_factors"]:
                if factor["name"] == "gnn_score":
                    gnn_scores.append(factor["value"])
                    by_group[group]["gnn"].append(factor["value"])
                if "confidence" in factor:
                    confidences[factor["confidence"]] += 1

    assert n > 0, f"{args.input} contained no records"
    both = signal_sets.get("gnn+traffic", 0)
    gnn_only = signal_sets.get("gnn", 0)

    log.info("Wrote %s fused records to %s", f"{n:,}", args.output)
    log.info("--- signal coverage ---")
    log.info(
        "both signals (gnn+traffic): %s (%.1f%%)", f"{both:,}", 100 * both / n
    )
    log.info("GNN only:                   %s (%.1f%%)", f"{gnn_only:,}", 100 * gnn_only / n)
    if confidences:
        log.info(
            "traffic confidence: %s",
            ", ".join(f"{k}={confidences[k]:,}" for k in CONFIDENCE_LEVELS if confidences[k]),
        )
    log.info("--- tiers ---")
    for tier in ("high", "medium", "low"):
        log.info("%-6s %s (%.1f%%)", tier, f"{tiers[tier]:,}", 100 * tiers[tier] / n)
    log.info("--- score shift, overall ---")
    log.info(
        "mean GNN score=%.6f -> mean fused score=%.6f (%+.6f)",
        sum(gnn_scores) / n,
        sum(fused_scores) / n,
        sum(fused_scores) / n - sum(gnn_scores) / n,
    )
    log.info("--- score shift, by signals_used ---")
    for group in ("gnn", "gnn+traffic"):
        fused = by_group[group]["fused"]
        original = by_group[group]["gnn"]
        if not fused:
            continue
        log.info(
            "%-11s n=%-8s gnn mean=%.6f median=%.6f -> fused mean=%.6f median=%.6f "
            "(mean %+.6f)",
            group,
            f"{len(fused):,}",
            statistics.fmean(original),
            statistics.median(original),
            statistics.fmean(fused),
            statistics.median(fused),
            statistics.fmean(fused) - statistics.fmean(original),
        )
    # A GNN-only record is returned unchanged, so its fused and input scores must
    # match exactly. Any drift means a missing signal reached the arithmetic.
    passthrough = by_group["gnn"]
    if passthrough["fused"]:
        drift = max(
            abs(f - g) for f, g in zip(passthrough["fused"], passthrough["gnn"])
        )
        log.info(
            "GNN-only passthrough check: max |fused - gnn| = %.2e across %s records%s",
            drift,
            f"{len(passthrough['fused']):,}",
            "" if drift <= 1e-6 else "  <== NONZERO, missing signal is leaking",
        )
        assert drift <= 1e-6, (
            f"GNN-only scores drifted from their input by up to {drift}; a missing "
            "traffic signal is being folded into the score"
        )
    log.info(
        "Traffic signal is STUBBED (%s). Replace get_traffic_signal in "
        "src/fusion.py with a real lookup.",
        f"{100 * (1 - missing_rate):.0f}% synthetic coverage",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
