# Threshold experiment: `CLUSTER_MIN_SIGNALS` 1 → 2 (Week 11)

A single-variable, pre-registered experiment testing the hypothesis from
[`accuracy-gap.md`](accuracy-gap.md): the `sybil_cluster` flag fires on
*everyone* because one always-true (over-connected) graph signal trips it at
`CLUSTER_MIN_SIGNALS = 1`. Requiring **two** graph signals should drop legit
humans (only `cluster_size` fires → 1 signal) below the flag while keeping
sybils (`cluster_size` + `counterparty_overlap` → 2 signals).

**Change under test:** `CLUSTER_MIN_SIGNALS: 1 → 2`. Nothing else — no other
threshold, weight, rule, or dataset change. The value is read from
`SCORING_CLUSTER_MIN_SIGNALS` (default `1`, so production/CI are unchanged); the
experiment toggles it per run.

## Metrics (same decision rule for every run)

- **Decision rule:** `human_likelihood == low → predicted sybil`; `medium/high →
  predicted human` (identical to `scoring-eval.md`).
- **Holdout TEST accuracy:** the Week-4 sybil-heavy held-out split (28 wallets),
  graph features computed over the full 105-wallet labeled set. This is the
  `scoring-eval.md` headline number.
- **Balanced accuracy:** 24 wallets (12 human + 12 sybil), scored as one
  `/verify/batch` (the batch is the graph context).
- Reported alongside: balanced sybil recall, balanced human false-positives,
  tier distribution.

> **Baseline drift, flagged.** The holdout TEST baseline measured **82.14%**
> (23/28) today, vs the **78.57%** recorded in `scoring-eval.md`. The config is
> identical (threshold = 1); the difference is **one wallet** and comes from
> **live on-chain data drift** — all 105 wallets were re-ingested fresh for this
> experiment and wallets accrue activity between eval runs. The experiment stays
> valid because baseline/change/ablation were all measured in the **same data
> snapshot**. Red lines are applied against both 78.6% and this 82.14%.

## Results

| metric | baseline `=1` | **change `=2`** | ablation `=1` |
| --- | --- | --- | --- |
| holdout TEST accuracy | 82.14% (23/28) | **82.14%** (23/28) | 82.14% |
| holdout TRAIN accuracy | 76.62% | 71.43% | 76.62% |
| balanced accuracy | 54.17% | **62.50%** | 54.17% |
| balanced sybil recall | 75% (9/12) | 66.7% (8/12) | 75% |
| balanced human false-positives | 8/12 | **5/12** | 8/12 |
| balanced tiers | bronze 17 / silver 7 | bronze 13 / silver 9 / gold 2 | bronze 17 / silver 7 |

## Red lines

| red line | result | verdict |
| --- | --- | --- |
| Holdout accuracy drops > 5 pts (below 73.6%) → revert | TEST **unchanged** at 82.14% | ✅ held |
| Balanced does NOT improve ≥ 5 pts → revert | **+8.33 pts** (54.17 → 62.50) | ✅ held |

Neither red line was crossed, so the change was **not** reverted.

## Ablation

Toggling back to `=1` reproduced the baseline **exactly** (82.14% / 54.17% /
tiers bronze 17 silver 7). The measurement is deterministic on a fixed data
snapshot, so the +8.33-pt balanced gain is attributable to **this change alone**.

## Honest interpretation

- **Real but modest, and the gap is NOT closed.** Balanced accuracy rose
  54.2% → 62.5% (+8.3 pts). That is above the marginal band, but it is still far
  from the 78.6% cluster-aware headline — the change **partially narrows** the
  gap, it does not close it.
- **The mechanism behaved as predicted.** The win comes from **3 fewer humans
  wrongly flagged** (false-positives 8/12 → 5/12): requiring 2 graph signals
  stops the over-connected `cluster_size` from tripping `sybil_cluster` on its
  own, and 2 humans even recover to `gold`.
- **Tradeoffs, stated plainly (not spun):**
  - Balanced **sybil recall dropped** 75% → 66.7% (one fewer sybil caught) — a
    precision/recall tradeoff: firing the flag less eagerly helps humans but
    misses a borderline sybil.
  - Holdout **TRAIN accuracy dropped 5.2 pts** (76.6% → 71.4%). On a
    sybil-dominated split, predicting "sybil" less often costs accuracy. The
    held-out **TEST** number — the one that matters — was unchanged, but the
    train drop is real and worth noting.
- **Net:** a genuine, low-risk improvement on balanced accuracy with no
  held-out-test regression, at the cost of slightly lower sybil recall. It
  validates the diagnosis but does not, by itself, restore cluster-aware
  accuracy on balanced data.

## Reproduce

```bash
# all 105 labeled wallets ingested once (needs a real ETHERSCAN_API_KEY), then:
SCORING_CLUSTER_MIN_SIGNALS=1 python measure_threshold.py   # baseline
SCORING_CLUSTER_MIN_SIGNALS=2 python measure_threshold.py   # change
SCORING_CLUSTER_MIN_SIGNALS=1 python measure_threshold.py   # ablation
```

(`measure_threshold.py` is the scratch harness from this experiment; it reuses
`evaluate_scoring` for the holdout and `score_batch_with_graph` for the balanced
set.) Numbers drift slightly with live on-chain data; the direction
(balanced +8 pts, holdout TEST flat, train −5 pts) is the finding.

## Status of the change

Validated and recommended, but **not shipped as the default** in this commit:
`CLUSTER_MIN_SIGNALS` still defaults to `1`. Flipping the default to `2` is a
production scoring-behavior change (needs a `SCORER_VERSION` bump and test
updates) — a separate decision. See [`scoring-v2-proposal.md`](scoring-v2-proposal.md).
