"""Configuration constants for the Elliptic PPR pipeline.

This module holds constants only, so that both the pipeline and any downstream
stage can import it without triggering data loading or heavy dependencies.
"""

from pathlib import Path

# --------------------------------------------------------------------------- #
# Paths
# --------------------------------------------------------------------------- #

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"
DATA_RAW = DATA_DIR / "raw"
DATA_PROCESSED = DATA_DIR / "processed"

# `EllipticBitcoinDataset` inherits `Dataset.raw_dir == root/raw`, so passing
# root=DATA_DIR makes PyG read the Kaggle CSVs in place out of data/raw/ and
# write its own cache into data/processed/. No duplicate download is needed.
PYG_ROOT = DATA_DIR

RAW_FEATURES = "elliptic_txs_features.csv"
RAW_EDGELIST = "elliptic_txs_edgelist.csv"
RAW_CLASSES = "elliptic_txs_classes.csv"
RAW_FILES = (RAW_FEATURES, RAW_EDGELIST, RAW_CLASSES)

NODE_MAPPING_PARQUET = DATA_PROCESSED / "node_mapping.parquet"
PPR_SCORES_PARQUET = DATA_PROCESSED / "ppr_scores.parquet"

KAGGLE_DATASET = "ellipticco/elliptic-data-set"

# --------------------------------------------------------------------------- #
# Expected dataset shape
#
# These are tripwires. If a future dataset revision or a truncated download
# changes any of them, the pipeline should fail loudly rather than silently
# produce scores over the wrong graph.
# --------------------------------------------------------------------------- #

N_NODES = 203_769
N_EDGES = 234_355
N_FEATURES = 165

# --------------------------------------------------------------------------- #
# Labels and split
# --------------------------------------------------------------------------- #

# The raw CSV and PyG use *different* label encodings, which is the single most
# common source of inverted-class bugs when working with this dataset:
#
#   raw elliptic_txs_classes.csv : '1' = illicit, '2' = licit, 'unknown'
#   torch_geometric `data.y`     :  1  = illicit,  0  = licit,  2 = unknown
#
# Note that raw '2' (licit) becomes 0, not 2. Always seed from the PyG encoding
# via the LABEL_* constants below.
LABEL_LICIT = 0
LABEL_ILLICIT = 1
LABEL_UNKNOWN = 2

# Mirrors the mapping inside `torch_geometric.datasets.elliptic`.
RAW_CLASS_MAP = {"unknown": 2, "1": 1, "2": 0}

LABEL_NAMES = {
    LABEL_LICIT: "licit",
    LABEL_ILLICIT: "illicit",
    LABEL_UNKNOWN: "unknown",
}

EXPECTED_LABEL_COUNTS = {
    LABEL_ILLICIT: 4_545,
    LABEL_LICIT: 42_019,
    LABEL_UNKNOWN: 157_205,
}

# Temporal split boundary. PyG already applies exactly this rule:
#   train_mask = (time_step < 35) & (y != 2)
#   test_mask  = (time_step >= 35) & (y != 2)
# The pipeline uses PyG's masks and asserts this boundary rather than
# reimplementing the split.
TIME_STEP_TRAIN_MAX = 35

# --------------------------------------------------------------------------- #
# PPR parameters
# --------------------------------------------------------------------------- #

PPR_ALPHA = 0.85

# NetworkX tests convergence as `err < N * tol`, so at N=203,769 the library
# default of 1e-6 is very loose relative to per-node scores of order 1e-5.
# Tightening to 1e-8 keeps numerical noise well below the signal.
PPR_TOL = 1e-8

# Raised from the NetworkX default of 100 so the tighter tolerance above cannot
# trip PowerIterationFailedConvergence.
PPR_MAX_ITER = 200

# Ranking method for the percentile column. "average" places the whole block of
# unreachable (exactly-zero) nodes at its mass midpoint.
RANK_METHOD = "average"

# --------------------------------------------------------------------------- #
# Per-step leave-one-out PPR
#
# Every Elliptic edge connects two transactions in the SAME time step: 234,355
# of 234,355, with zero edges crossing the step-35 train/test boundary. The
# graph is therefore 49 disconnected components, one per step, and a PPR seeded
# only on training-window nodes is identically 0.0 on every test node -- no
# amount of propagation can cross the boundary.
#
# The feature is instead seeded per time step, from that step's own illicit
# nodes, so a test-step node is scored by its same-step illicit neighbours.
# Leakage is controlled by leave-one-out: a node is never a member of its own
# seed set, so its score depends only on OTHER nodes' labels.
PPR_DIRECTIONS = ("fwd", "rev")

# Tolerance for the single-seed column runs. Tighter than the global PPR tol
# because each per-step subgraph is small and the columns are summed.
PPR_LOO_TOL = 1e-10
PPR_LOO_MAX_ITER = 500

# --------------------------------------------------------------------------- #
# Validation split, carved from the training window only
#
# Validation is time steps 28-34; training proper becomes steps 1-27. The test
# window (35-49) is untouched.
#
# Step 28 is chosen because it puts 16.6% of labeled training nodes in
# validation -- the closest to a 20% target among boundaries that keep a usable
# number of positives (1,005 illicit, 20.22% of the validation split). Earlier
# boundaries give a larger validation set at the cost of training data (step 26
# yields 19.0%), while later ones collapse it (step 33 leaves 3.2% and only 60
# positives, too few for a stable F1).
#
# The cut is temporal rather than random, so validation is strictly later in
# time than training. That mirrors the real train/test relationship and makes
# the validation curve informative about temporal shift; a random cut would
# instead leak same-step neighbours, since every Elliptic edge is intra-step.
TIME_STEP_VAL_START = 28

# --------------------------------------------------------------------------- #
# Optional recency weighting
#
# Per-node training loss weight = RECENCY_DECAY ** (max_train_step - node_step),
# so later training steps count for more. The intent is to bias the model toward
# the most recent training era, which is closest in time to the test window, and
# so to reduce the temporal-shift loss that the curve diagnostic identified as
# the dominant error term (val-test gap ~0.51 against train-val ~0.09).
#
# The trade-off is effective sample size. Over training steps 1-34:
#   decay=0.90 -> step-1 weight 3.09e-02, effective n ~14,232 of 29,894
#   decay=0.95 -> step-1 weight 1.84e-01, effective n ~23,227 of 29,894
# Weighting also shifts the weighted illicit share (11.58% unweighted, to 16.04%
# at 0.90 and 14.28% at 0.95), so pos_weight must be recomputed FROM the
# weighted counts or the class-balance change would confound the recency effect.
#
# None disables weighting entirely and reproduces the unweighted baseline.
RECENCY_DECAY_CANDIDATES = (0.9, 0.95)
