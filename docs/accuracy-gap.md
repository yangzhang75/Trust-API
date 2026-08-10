# Accuracy gap: single `/verify` vs `/verify/batch` (Week 11)

Week 10 found single-wallet `/verify` scores ~54% on a balanced human/sybil set
(vs the engine's 78.6% cluster-aware headline) because graph features can't be
computed from one wallet. Week 11 built `/verify/batch` to populate those
features across a batch. This reproduces the measurement.

**Honest headline: batch scoring did NOT close the gap on this test.** It
populates graph features and clearly changes scores — but on a balanced 12/12
set it does not separate humans from sybils any better than single `/verify`.
Below is exactly what happened and why.

## The measurement

Same 24 wallets as Week 10 (12 labeled human, 12 labeled sybil), live Trust API,
scorer `0.4.0-graph`. "Accuracy" = human/sybil classification using the
`sybil_suspected` flag as the reject signal (same framing as Week 10).

| path | accuracy | sybil recall | tier distribution |
| --- | --- | --- | --- |
| single `/verify` (one at a time) | **54.2%** (13/24) | **8.3%** (1/12) | silver 15 / gold 7 / bronze 2 |
| `/verify/batch` (24 together) | **54.2%** (13/24) | **8.3%** (1/12) | **bronze 17 / silver 7** |

Per-label under the batch — humans and sybils are **still indistinguishable**:

| label | silver | gold | bronze |
| --- | --- | --- | --- |
| human (12) | 4 | 0 | 8 |
| sybil (12) | 3 | 0 | 9 |

The batch **did** run the graph pass — tiers moved hard (gold 7 → 0, bronze
2 → 17) and `graph_context_size` was **23 for 23 of the 24 wallets** (one giant
connected component). So graph features were populated and fed into scoring; the
problem is what they did.

## Why it didn't reach 78.6% — analysis (not smoothed over)

**1. An arbitrary batch over-connects into one component.** The cluster edge
rule links any two wallets that share a top funder *or* a counterparty *or* a
direct transfer. Two dozen real wallets almost all touch mainstream
counterparties (popular DEXs, stablecoins, bridges), so they all link —
`graph_context_size = 23`. When *everyone* is "clustered," the cluster-size
signal fires for humans and sybils alike and drops the whole batch to bronze.
It penalizes indiscriminately instead of isolating farming clusters.

**2. The 78.6% baseline is Sybil-dominated; a balanced set is inherently
harder.** `scoring-eval.md` flags that its TEST split is class-imbalanced (far
more sybils than humans), so its headline accuracy is sybil-dominated —
predicting "sybil/bronze" often is *rewarded* there. The graph-aware scorer's
tendency to push clustered wallets toward bronze looks great on a sybil-heavy
split and like a coin-flip (≈50%) on our balanced 12/12 set. Batch scoring
faithfully reproduces that tendency; the balanced set just exposes it.

**3. Even a real cluster only drops tier — it doesn't set the flag.** Batching a
verified 5-member sybil cluster (`hop-543`) alone gives `graph_context_size = 5`
for all and **all bronze** — the *right* low-trust outcome — but
`sybil_suspected` still fires **0/5**. The flag's a-priori thresholds
(`docs/scoring.md`) aren't met even on a genuine cluster of this size, so
flag-based recall stays low regardless of batching.

## What this means

- **The endpoint works as built** (graph features populate; `graph_context_size`
  tracks real component sizes: 5 for a real cluster, 23 for an over-connected
  mix). This is not a wiring bug — it's a property of the scorer + cohort.
- **Batching is necessary but not sufficient.** Graph features only discriminate
  when the batch is a *meaningful neighborhood*. An arbitrary cohort adds
  spurious edges and degenerates to "everyone bronze."
- **The gap is not closed by this change alone.** Honestly: to actually lift
  balanced accuracy we would need (a) an edge rule that ignores high-degree
  mainstream counterparties (so incidental sharing doesn't over-connect), (b)
  cluster-aligned batching (group by campaign/time/referrer, not at random), and
  (c) re-tuning the `sybil_suspected` thresholds against a balanced set. Those
  are scoring-logic changes, explicitly out of scope for Week 11 (which must not
  touch scoring rules or thresholds).

## Reproduce

```bash
RATE_LIMIT_PER_MINUTE=5000 docker compose up -d api      # needs a real ETHERSCAN_API_KEY
# then run the 24-wallet single-vs-batch comparison (scratch script in the PR notes),
# or by hand: POST /verify per wallet, then one POST /verify/batch of all 24.
```

Numbers vary slightly with live on-chain data; the pattern (batch ≈ single on a
balanced set, everyone → bronze) is stable.
