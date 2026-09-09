# SentriX — Bitcoin Address Risk Scoring

A graph-based risk signal for Bitcoin transactions, computed over the
[Elliptic](https://www.kaggle.com/datasets/ellipticco/elliptic-data-set)
transaction dataset.

The pipeline computes **Personalized PageRank (PPR)** proximity-to-illicit
features, joins them onto Elliptic's 165 raw node features, trains a GraphSAGE
classifier on the temporal split, and exports per-transaction risk records.

PPR is seeded **per time step** from that step's confirmed-illicit transactions,
with leave-one-out so a node is never its own seed. That design is forced by the
data: every Elliptic edge stays inside one time step, so a PPR seeded only on the
training window is identically zero on every test node — see
[Method](#ppr-direction-and-seeding--why-it-is-per-step-not-train-seeded).

Adding the four PPR columns improves held-out illicit-class F1 from
0.5340 +/- 0.0186 to **0.6943 +/- 0.0204** (+0.1603) and AUC from 0.8966 to
**0.9570** (+0.0604), measured over 3 seeds with no overlap between the two
configurations on any seed.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Developed against **Python 3.14**. The `torch==2.14.0` pin is the one most
likely to need adjustment on another platform — check that a wheel exists for
your interpreter and OS before changing anything else.

`scipy` is required even though this project never imports it: `nx.pagerank`
dispatches to its SciPy sparse implementation.

`scikit-learn` is intentionally **not** a dependency: the min-max is two numpy
lines, the percentile is `pandas.rank`, and the train/test split comes from PyG.
Add `scikit-learn==1.9.0` when a model stage lands.

## Kaggle credentials

The PyG loader can download its own preprocessed copy of Elliptic, but that copy
has already discarded the original `txId` values. The Kaggle release keeps them,
which is what makes scores traceable to real transactions.

1. Sign in at [kaggle.com](https://www.kaggle.com), open **Settings → API**.
2. Click **Create New Token** to download `kaggle.json`.
3. Install it:
   ```bash
   mkdir -p ~/.kaggle
   mv ~/Downloads/kaggle.json ~/.kaggle/kaggle.json
   chmod 600 ~/.kaggle/kaggle.json
   ```

Alternatives: set `KAGGLE_CONFIG_DIR` to the directory holding `kaggle.json`, or
export `KAGGLE_USERNAME` and `KAGGLE_KEY`.

You must also accept the dataset's terms once on its Kaggle page.

## Running

```bash
python -m src.ppr        # 1. PPR graph features   -> data/processed/ppr_scores.parquet
python -m src.features   # 2. join raw + PPR       -> data/processed/features_enriched.pt
python -m src.train      # 3. train GraphSAGE      -> data/processed/checkpoints/
python -m src.ablation   # 4. raw vs enriched      -> data/processed/ablation.md
python -m src.export     # 5. per-node JSON        -> output/scores.jsonl
python -m src.curves     # 6. train/val/test curves -> data/processed/curves.csv
```

Step 6 is a diagnostic rather than part of the pipeline: it carves a validation
split from the training window and logs metrics every epoch. See the overfitting
section below.

Each step reads the previous step's output and fails with a pointer to the step
it needs, so running them out of order is safe. `src.ablation` trains both
configurations itself, so it supersedes a plain `src.train` run; `src.train`
alone is useful for iterating on one configuration.

Approximate runtimes on CPU: PPR ~3.5 min (9,090 single-seed solves), features
~5 s, training ~9 min per configuration, the 3-seed ablation ~55 min, export
~5 s, curves ~20 min for both configurations.

If the raw CSVs are missing, fetch them first:

```bash
python scripts/fetch_kaggle.py
```

Expected layout after the fetch:

```
data/
  raw/
    elliptic_txs_features.csv     # 203,769 rows, no header
    elliptic_txs_edgelist.csv     # 234,355 rows + header
    elliptic_txs_classes.csv      # 203,769 rows + header
  processed/
    data.pt                       # PyG's cache (written on first load)
    node_mapping.parquet
    ppr_scores.parquet
    features_enriched.pt
    ablation.md
    checkpoints/graphsage_{raw,enriched}.pt
output/
  scores.jsonl
```

The three CSVs must sit **directly** in `data/raw/`, not in a subdirectory.
`fetch_kaggle.py` relocates them if the archive nests them, since the Kaggle zip
has shipped them inside an `elliptic_bitcoin_dataset/` folder at times.

**Troubleshooting — "it started downloading from data.pyg.org":** that means PyG
did not find the CSVs where it looks. `EllipticBitcoinDataset` does not override
`Dataset.raw_dir`, so its raw directory is `root/raw`; the pipeline passes
`root=data/`, which resolves to `data/raw/`. If a file is missing or misnamed,
PyG falls back to its own download. `src.ppr` pre-checks for all three files and
exits with a pointer to the fetch script.

## Outputs

### `data/processed/ppr_scores.parquet`

One row per node, all 203,769 covered, keyed by `txId`:

| Column | Type | Meaning |
| --- | --- | --- |
| `txId` | int64 | Original Elliptic transaction id |
| `node_index` | int64 | PyG node index (0..203,768) |
| `time_step` | int16 | Elliptic time step, 1-49 |
| `label` | int8 | PyG encoding: 1 illicit, 0 licit, 2 unknown |
| `split` | category | `train` / `test` / `unlabeled` |
| `ppr_fwd_raw` | float64 | Forward PPR mass; exactly 0.0 if unreachable |
| `ppr_fwd_score` | float64 | Log-compressed, min-max normalized to [0, 1] |
| `ppr_fwd_percentile` | float64 | Rank-based percentile |
| `ppr_rev_raw` | float64 | Reverse-direction PPR mass |
| `ppr_rev_score` | float64 | Log-compressed, min-max normalized to [0, 1] |
| `ppr_rev_percentile` | float64 | Rank-based percentile |

### Other artifacts

- `data/processed/node_mapping.parquet` — `txId`, `node_index`, `time_step`.
- `data/processed/features_enriched.pt` — 203,769 x 169 float32 tensor
  (165 raw + 4 PPR columns), plus feature names and `tx_ids`.
- `data/processed/ablation.md` — the multi-seed raw-vs-enriched comparison.
- `data/processed/curves.csv` — per-epoch train/validation/test metrics for both
  configurations, 400 rows (200 epochs x 2 configs).
- `output/scores.jsonl` — one risk record per node; schema in `src/export.py`.
  `graph_context.ppr_score` carries the **forward** direction, since the schema
  has a single slot; the reverse column stays in the parquet.

## Label encoding — read this first

The raw CSV and PyG use **different** label encodings. This is the most common
source of silently inverted-class bugs with this dataset.

| Meaning | Raw `elliptic_txs_classes.csv` | PyG `data.y` / our `label` column |
| --- | --- | --- |
| illicit | `'1'` | `1` |
| licit | `'2'` | `0` |
| unknown | `'unknown'` | `2` |

Raw `'2'` (licit) becomes `0`, **not** `2`. Always filter on the PyG encoding via
the `LABEL_*` constants in [src/config.py](src/config.py). Seeding on the raw
convention would seed licit transactions and invert the entire signal.

## Method

### PPR direction and seeding — why it is per-step, not train-seeded

The original design seeded PPR from illicit **training** nodes and propagated
along payment flow. Measured on the real data, that produces a feature that is
**identically 0.0 for every test node**, because:

> **All 234,355 Elliptic edges connect two transactions in the same time step.
> Zero edges cross the step-35 train/test boundary, in either direction.**

The graph is 49 disconnected per-step components. Train nodes (steps 1-34) and
test nodes (steps 35-49) share no edge, so no propagation from training seeds can
reach a test node at any `alpha`, `tol`, `max_iter`, or hop count. Both
directions were measured and both gave 0.0% nonzero coverage on all 16,670 test
nodes.

The feature is therefore seeded **per time step**, from that step's own illicit
nodes, so a test-step node is scored by its same-step illicit neighbours.

**Leakage control is leave-one-out.** A node is never a member of its own seed
set. This matters more than it sounds: with self-seeding, 100% of illicit nodes
scored nonzero and forward separation read 75.79x — almost entirely the seeds
scoring themselves. Excluding self gives 13.0% coverage and 9.45x, which is the
honest number.

The exclusion is exact, not approximate. PPR is linear in the personalization
vector, so for uniform seeds `S`, `score(v | S) = (1/|S|) * sum_{s in S} ppr_s(v)`.
Running one single-seed PPR per illicit node and caching the column sums lets any
node be rescored against `S \ {v}` by subtracting its own column and
renormalizing by `|S| - 1`.

**Both directions ship**, as `ppr_fwd_*` and `ppr_rev_*`. Leave-one-out, test
split:

| | Forward (downstream of illicit) | Reverse (sent toward illicit) |
| --- | --- | --- |
| nonzero nodes | 2,705 (1.33%) | 11,247 (5.52%) |
| illicit mean score | 0.108062 | 0.146742 |
| licit mean score | 0.011434 | 0.029091 |
| **separation** | **9.45x** | **5.04x** |
| illicit nonzero | 13.0% | 18.7% |
| percentile floor | 0.4934 | 0.4724 |

They are complementary rather than redundant: reverse reaches 4.2x more nodes,
forward gives sharper separation. The ablation (below) shows the pair earns its
place.

### Other choices

- **Graph.** All 203,769 nodes and all edges, as an `nx.DiGraph` following
  payment flow, with the reverse view built by `Graph.reverse()`.
- **Dangling mass.** Redistributed to the seed vector (`dangling=personalization`).
- **Start vector.** `nstart=personalization`, which is what makes unreachable
  nodes score *exactly* zero. `nx.pagerank` dispatches to its SciPy
  implementation, whose iteration is
  `x = alpha * (x @ A + dangling) + (1 - alpha) * p`. The default start is
  uniform `1/N`, so every node begins with mass and an unreachable node only
  decays by `alpha` per pass. Measured on a synthetic 200k-node graph: with the
  default start, one unreachable node still held `1.07e-13` at convergence; with
  `nstart` on the seeds the exact-zero count matched the unreachable count.
- **Parameters.** alpha = 0.85; `tol = 1e-10`, `max_iter = 500` for the
  single-seed column runs.

### The score transform

```python
scale = 1.0 / raw[raw > 0].min()   # smallest nonzero -> 1.0
z     = np.log1p(raw * scale)      # zeros -> exactly 0.0
ppr_score = z / z.max()
```

`log1p` on raw PPR is a **no-op** — `log1p(1e-6)/1e-6 == 1.000000` to six
decimals — so applying it directly would quietly reduce the step to a min-max of
the raw scores. Scaling first is what gives the logarithm something to compress.
It also avoids the epsilon problem: with `log(x + eps)` the zero block lands at
`log(eps)`, making the distribution shape depend on an arbitrary constant, while
`log1p(0)` is exactly 0.0.

### GNN and class imbalance

GraphSAGE, 3 `SAGEConv` layers, hidden dim 128, dropout 0.3, BatchNorm between
layers, single logit per node. Trained full-batch on labeled nodes only, using
the temporal split — never a random split, which would let the model see
same-step neighbours of its own evaluation nodes and leak almost perfectly.

**Imbalance is handled with a weighted loss** (`pos_weight = n_neg/n_pos = 7.63`),
not oversampling. This is full-batch node classification on a fixed graph: every
node participates in every forward pass, so there is no sampler to rebalance.
Duplicating minority nodes would also duplicate them in the message-passing
graph and distort the neighbourhood structure the GNN reads. Reweighting the loss
changes the gradient without touching the topology.

Training is a **two-stage protocol**, and both stages matter:

1. **Choose the epoch count.** Fit on inner-train (time steps 1-27) and stop on
   **validation F1** (steps 28-34) with patience 15 and a 30-epoch warmup floor.
2. **Refit for real.** Retrain from scratch on the **full** training window
   (steps 1-34) for exactly the epoch count stage 1 chose.

The test window (35-49) is never read for any decision in either stage.

**Why two stages rather than just keeping the stage-1 model.** Stage 1 has to
hold out steps 28-34 to have a validation signal at all — but those are the
training steps closest in time to the test window, and the drift diagnostic
showed recency is what matters most here. Keeping the stage-1 model costs
enriched test F1 0.6954 -> 0.4354, purely from the lost 16.6% of training data.
Refitting keeps the stopping decision honest while paying no data penalty.

**Why the warmup floor.** Validation F1 spikes during warmup: the enriched
configuration hits 0.645 at epoch 2, dips to 0.462, and does not recover until
epoch 18. An unguarded patience of 15 expires inside that dip, stopping at epoch
17 having selected epoch 2 — which was measured, and produced test F1 0.4354.
The floor delays the patience counter to epoch 30 so a warmup spike cannot end
training. Reaching the true validation peak would otherwise require tolerating a
43-epoch no-improvement run (enriched) or 103 (raw), well beyond any reasonable
patience.

Regularization: **dropout 0.3** between SAGEConv layers (after BatchNorm and
ReLU) and **L2 weight decay 1e-4** in the Adam optimizer.

Standardization is fit on whichever split is training at the time — inner-train
in stage 1, the full window in stage 2 — never on test.

## Ablation result

Test set, illicit class, **3 seeds (42, 1337, 2024)**, mean +/- sample sd.
Two-stage protocol in both configurations (see the training section); test is
never read for any decision.

| Metric | 165 raw | Enriched (169) | Delta of means |
| --- | --- | --- | --- |
| Precision | 0.4409 +/- 0.0231 | 0.6053 +/- 0.0274 | **+0.1643** |
| Recall | 0.6774 +/- 0.0070 | 0.8147 +/- 0.0192 | **+0.1373** |
| F1 | 0.5340 +/- 0.0186 | 0.6943 +/- 0.0204 | **+0.1603** |
| AUC | 0.8966 +/- 0.0032 | 0.9570 +/- 0.0040 | **+0.0604** |

Per seed:

| Seed | raw F1 | enriched F1 | raw AUC | enriched AUC |
| --- | --- | --- | --- | --- |
| 42 | 0.5542 | 0.7159 | 0.8995 | 0.9611 |
| 1337 | 0.5304 | 0.6916 | 0.8971 | 0.9568 |
| 2024 | 0.5175 | 0.6753 | 0.8931 | 0.9532 |

**Every delta clears the combined spread**, and the two configurations do not
overlap on any seed: the worst enriched F1 (0.6753) exceeds the best raw F1
(0.5542) by 0.1211. The F1 delta of +0.1603 is roughly 4x the summed standard
deviations (0.0390). AUC separates even more cleanly — the two ranges are
0.8931-0.8995 and 0.9532-0.9611, with no possible overlap.

The gain is concentrated in a minority of nodes — the columns are nonzero for
only 13.0% (forward) and 18.7% (reverse) of illicit test nodes — so where they
fire they are close to decisive rather than nudging every node a little.

With n=3 the standard deviation is itself a coarse estimate; read it as a spread
indicator rather than a confidence interval. The non-overlap argument does not
depend on it.

**This table supersedes all earlier ablation numbers in this project.** Earlier
versions selected the checkpoint on train F1, which is not a defensible stopping
criterion; those figures (enriched F1 0.7068 +/- 0.0068) are not comparable to
these. Raw fell further than enriched under the change (0.6006 to 0.5340) while
its AUC rose (0.8817 to 0.8966), which indicates the earlier raw number was
benefiting from a favourable 0.5-threshold position rather than from better
ranking.

### Is the selected epoch a lucky one?

Test F1 was swept across refit epoch counts 1-100 at seed 42 to check whether
the result sits on a narrow spike. It does not. For the enriched configuration
the neighbourhood of the selected epoch is a broad plateau:

| Window around selected epoch | min | max | mean | spread |
| --- | --- | --- | --- | --- |
| +/-5 epochs | 0.6831 | 0.7437 | 0.7140 | 0.0606 |
| +/-10 epochs | 0.6657 | 0.7437 | 0.7101 | 0.0780 |

Every epoch within +/-10 scores at least 0.6657, and epochs 45-100 all land in
0.67-0.74. The selected epoch scored 0.6954, *below* its own +/-5 mean of 0.7140
and 0.0483 below the sweep's best — so validation selection picked a mildly
unlucky point inside a good region, which is the reassuring direction.

The raw configuration is noisier (+/-5 spread 0.1188) but its AUC stays flat at
0.887-0.905 across the same window, so that instability is an artefact of the
fixed 0.5 threshold rather than of the model's ranking.

That sweep is seed 42 only: it establishes stability across epoch choice, not
across initialization. The 3-seed table above covers the second axis.

## Overfitting investigation — the gap is temporal shift, not overfitting

A validation split was carved from the **training window only** (time steps
28-34, with steps 1-27 as inner-train) to test whether the train-to-test gap
(train F1 ~0.98 against test F1 ~0.70) comes from overfitting during training or
from distribution shift into the later test era. The real test split (35-49) was
untouched. Step 28 puts 16.6% of labeled training nodes in validation while
keeping 1,005 illicit positives; the cut is temporal rather than random, because
every Elliptic edge is intra-step and a random cut would place same-step
neighbours on both sides.

`python -m src.curves` records train, validation and test metrics at every
epoch. Final-epoch gaps at seed 42:

| Config | train | val | test | train-val | val-test |
| --- | --- | --- | --- | --- | --- |
| raw | 0.9656 | 0.8173 | 0.2677 | +0.1483 | **+0.5496** |
| enriched | 0.9852 | 0.8986 | 0.3896 | +0.0866 | **+0.5090** |

**The verdict is shift, not overfitting.** Validation never turns down: its slope
over the last 50 epochs is *positive* in both configurations (+0.001005 raw,
+0.000129 enriched per epoch), and validation peaks late — epoch 183/200 for raw
and 154/200 for enriched — finishing within 0.0056 (enriched) of its peak.
Overfitting would show validation declining while train climbs; raw's train slope
is in fact slightly negative while validation rises.

The val-test gap is about 6x the train-val gap, so nearly all the loss occurs at
the train-era to test-era boundary rather than between training and held-out data
from the same era. Most of the remaining train-val gap is expected baseline
rather than overfitting, because validation is a harder slice: 20.22% illicit
against 9.86% in inner-train.

Validation is nonetheless a *good* selector — it just has no overfitting to
catch. For the enriched configuration the best-validation epoch (154) is exactly
the best-test epoch, and for raw it is within 0.0219 test F1 of optimal.

**What shipped as a result.** Stopping is now governed by validation F1 rather
than by a training metric that climbs to ~0.98 regardless. Adopting it required
two corrections that the aggregate curves alone did not reveal: a warmup floor,
because patience 15 otherwise expires inside an early validation dip, and a
stage-2 refit on the full training window, because permanently holding out steps
28-34 costs more test F1 than the better stopping rule gains. Both are measured
in the training section above. Regularization is dropout 0.3 between SAGEConv
layers and weight decay 1e-4.

The remaining and larger problem is the ~0.5 validation-to-test gap, which is
distribution shift rather than regularization. See
[Known limitations](#known-limitations).

## Known limitations

- **Temporal drift on the far test steps is not resolved by this fix.**
  Validation-based selection addresses when to stop training; it does not
  address the model degrading on the later time steps. The curve diagnostic
  measured a validation-to-test gap of roughly 0.51 against a train-to-validation
  gap of 0.09, so the dominant error term is the shift from the training era into
  the test era, not overfitting during training. Closing that properly needs
  periodic refitting on recent data — the live retraining loop described in the
  architecture document — rather than anything this training script can do.
- **Recency weighting was implemented and tested, but not adopted.** Per-node
  loss weights of `decay ** (max_train_step - node_step)` are available via
  `src.train --recency-decay`, with `weighted_class_weight` recomputing
  `pos_weight` from the weighted class mass so a class-balance shift cannot
  masquerade as a recency effect. Decay 0.9 and 0.95 were trialled. The
  comparison did not produce a clear confirmed winner, so the default stays
  `None` (unweighted) rather than shipping an unconfirmed change. Note the cost
  it would carry: decay 0.9 cuts the effective sample size from 29,894 to about
  14,232 nodes, and 0.95 to about 23,227.
- **The near-term versus far-term test comparison was single-seed only.** Any
  per-band reading is provisional. The far band is also nearly positive-free —
  steps 46-49 hold 116 illicit nodes in total and step 46 has just 2 of 712 — so
  band-level F1 there is noisy enough that a few points of movement is within
  noise for one seed.
- **Per-step test metrics are available** via `evaluate_per_step` in
  [src/train.py](src/train.py), returned as `per_step_test` on every training
  result, for anyone wanting to check where in the test window the model fails.

## Caveats

- **The percentile floor is ~0.49, and carries no information below it.** Every
  node with no reachable illicit node in its own time step scores exactly 0.0
  and they all tie, so with `method='average'` the whole block sits at one value:
  **0.4934** for `ppr_fwd_percentile`, **0.4724** for `ppr_rev_percentile`. Within
  that block the value is an artifact of block size — every node in it is equally
  unreachable. **Do not threshold below those values.** For a clean ranking,
  filter to `ppr_*_raw > 0` and rank within that subset.
- **Underflow makes some reachable nodes score exactly 0.0.** PPR mass decays by
  `alpha` per hop and divides across out-edges, so far enough from a seed it falls
  below the smallest representable float64. On the full graph under a single
  global seeding, 7 nodes underflowed at BFS distances **16, 16, 17, 18, 19, 20,
  21** against a maximum reachable depth of 21 — all at the extreme tail. Raising
  `max_iter` from 200 to 1000 changed nothing: the score vector was **bitwise
  identical** (`max abs diff = 0.0`, zero nodes changed), confirming float64
  underflow rather than a convergence failure. `report_underflow` logs these
  without failing the run; only the reverse case — an unreachable node *holding*
  mass — is fatal, since that means mass entered outside the seed set.
- **The PPR columns are sparse.** 98.67% of `ppr_fwd_score` and 94.48% of
  `ppr_rev_score` values are exactly 0.0. They are a high-value minority signal,
  not a dense feature.
- **`ppr_*_score` is a relative signal, not a probability.** Feed it to a model;
  do not read it as "chance of being illicit".
- **Scores are seed-set dependent.** Changing the split, the label source, or
  `alpha` changes every score. Recompute rather than mixing runs.
- **Per-step seeding measures same-step proximity**, not proximity to the
  training window. That is a deliberate change from the original design, forced
  by the intra-step edge structure documented above.
- **`risk_score` in `output/scores.jsonl` is not calibrated.** It is a sigmoid
  output selected for F1, so the 0.3/0.7 tier cut points are operational
  conventions, not probability statements.

## Validation

`validate_mapping` in [src/ppr.py](src/ppr.py) is a hard gate — nothing is
written if it fails. It checks node and edge counts, label counts against known
Elliptic totals, edge-endpoint coverage, multiset equality between the raw
edgelist mapped through the derived mapping and `data.edge_index`, and the
train/test mask boundary.

`check_zero_structure` then audits zero scores against an independent
multi-source BFS from the seeds, splitting the two possible disagreements
because they mean opposite things:

- `check_no_unreachable_mass` is a **hard assert**. A node with no directed path
  from any seed must hold exactly zero, since mass only enters at a seed. A
  nonzero value there means teleport or dangling mass escaped the seed set — the
  leakage indicator — so it fails the run.
- `report_underflow` is **informational**. A reachable node scoring zero is
  expected float64 underflow at long distance; it logs the count and distance
  distribution without failing. See the underflow caveat above for the measured
  numbers.

Two assumptions are worth calling out because they are unguarded in PyG itself:

- **Node index is features-CSV row order, not sorted `txId`.** PyG builds
  `{txId: i for i, txId in enumerate(feat_df['txId'].values)}`. Deriving the
  mapping by sorting would yield the right *number* of rows — passing a naive
  length check — while attributing every score to the wrong transaction. If a
  future PyG release changes its reindexing, the edge-set assertion fails loudly.
- **PyG never joins the classes CSV to the features CSV on `txId`.** `data.y`
  comes from classes-CSV row order while `x` comes from features-CSV row order,
  so `y` is correct only because both files happen to be emitted in the same
  order. The pipeline asserts this from both directions (positional and
  txId-join) and **aborts** on mismatch rather than falling back, because
  `train_mask` derives from `y`, so a misalignment would poison the seed set too.

After a run, the summary log reports each direction's nonzero count, `scale`,
`z_max`, percentile floor, and the illicit-vs-licit mean and separation on both
splits. Because seeding is leave-one-out, the test-split separation is a genuine
held-out read rather than seeds scoring themselves. If illicit does not come out
higher, suspect the label encoding first.

## Reproducibility

PPR is deterministic — no RNG. The GNN sets `torch.manual_seed(42)` and
`np.random.seed(42)`, so a rerun on the same data reproduces the ablation
numbers; results across different seeds have not been measured.

Recorded in each run's log and in the checkpoints: alpha, `tol`, `max_iter`,
per-direction `scale` and `z_max`, `pos_weight`, best epoch, and both splits'
metrics.

Measured runtimes on CPU (Python 3.14, torch 2.14.0+cpu, 203,769 nodes /
234,355 edges):

| Stage | Time |
| --- | --- |
| `src.ppr` | ~3.5 min (4,545 single-seed solves per direction) |
| `src.features` | ~5 s (reads the full ~690 MB features CSV) |
| `src.train` | ~5 min per configuration (141 epochs, early stop) |
| `src.ablation` | ~10 min (both configurations) |
| `src.export` | ~5 s |

Memory is dominated by the `nx.DiGraph` at roughly 250–400 MB (dict-of-dicts
overhead, ~1–1.5 KB/node), which is why `src.ppr` reads only the first two
columns of the features CSV while `src.features` reads all 167.
