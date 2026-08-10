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

## Why it didn't reach 78.6% — precise mechanism

> **Correction to an earlier version of this doc.** It first attributed the
> null result to the `sybil_suspected` flag "not firing." That was imprecise —
> `sybil_suspected` is driven by *behavioral* signals and is **not** affected by
> graph features. The graph features drive a **different** flag, `sybil_cluster`,
> and the real story (below) is that `sybil_cluster` fires on *almost everyone*.

### Two different sybil flags — don't conflate them

| flag | driven by | our batch measurement |
| --- | --- | --- |
| `sybil_suspected` | **behavioral** signals (`_sybil_signals`: low diversity, bot burst, new+inactive) — **not graph** | humans 0/12, sybils 1/12 |
| `sybil_cluster` | **graph** signals (`_graph_signals` ≥ `CLUSTER_MIN_SIGNALS`) | **humans 12/12, sybils 11/12** |

So graph features *are* used — `sybil_cluster` fires and drags tiers to bronze.
The failure is that it fires on **humans too**.

### The 4 graph features: thresholds vs measured means (batch of 12+12)

| graph feature | threshold to fire | human mean | sybil mean | discriminates? |
| --- | --- | --- | --- | --- |
| `cluster_size_estimate` | ≥ 3 (`CLUSTER_SIZE_MIN`) | **23.0** | **21.2** | ❌ both fire (over-connected) |
| `counterparty_overlap_score` | ≥ 0.30 (`COUNTERPARTY_OVERLAP_MIN`) | 0.095 | **0.469** | ✅ **only sybils fire** |
| `shared_funder_score` | ≥ 0.33 (`SHARED_FUNDER_MIN`) | 0.167 | 0.278 | ~ neither fires reliably |
| `funding_chain_depth` | ≥ 2 (`FUNDING_CHAIN_MIN`) | 0.0 | 0.083 | neither fires |

Two facts jump out:

1. **`cluster_size_estimate` is corrupted by over-connection.** The cluster edge
   rule links any two wallets that share a top funder *or* any counterparty *or*
   a direct transfer. Real wallets almost all touch mainstream counterparties
   (popular DEXs, stablecoins, bridges), so an arbitrary batch collapses into one
   giant component — cluster size ≈ 23 for humans *and* ≈ 21 for sybils. This
   signal is ≥ 3 for **everyone**, so it carries no discriminating information.

2. **`counterparty_overlap_score` genuinely discriminates** — 0.47 for sybils vs
   0.10 for humans. There *is* real signal in the graph features; it's just one
   feature, and it's being drowned out (next).

### `CLUSTER_MIN_SIGNALS = 1` is the dominant failure mode

`sybil_cluster` fires when **any one** of the four graph signals crosses its
threshold (`_graph_signals(f) >= CLUSTER_MIN_SIGNALS`, and `CLUSTER_MIN_SIGNALS`
is **1**). Because the corrupted `cluster_size` signal is true for everyone, one
signal is *always* met — so `sybil_cluster` fires on all 24 wallets, humans
included, and the whole batch is penalized to bronze. The one feature that
*does* separate humans from sybils (`counterparty_overlap`) never gets to matter,
because the flag has already fired on the useless one.

Net: **there is a discriminating feature, but a threshold of 1 lets a
non-discriminating (over-connected) feature trigger the flag for everyone,
drowning the signal.** Requiring ≥ 2 graph signals would, on these measured
means, drop humans (only `cluster_size` → 1 signal) below the flag while keeping
sybils (`cluster_size` + `counterparty_overlap` → 2 signals) — a hypothesis the
threshold experiment tests (see docs/threshold-experiment.md).

### Also: the 78.6% baseline is Sybil-dominated

Independently, `scoring-eval.md` flags that its TEST split is class-imbalanced
(far more sybils than humans), so its headline accuracy is sybil-dominated —
predicting bronze often is *rewarded* there. A balanced 12/12 set is inherently
harder for a scorer that pushes clustered wallets toward bronze; part of the
54% vs 78.6% gap is this measurement-set difference, not only the mechanism above.

## What this means

- **The endpoint works as built** — graph features populate and `sybil_cluster`
  reacts. This is not a wiring bug; it is a scoring-threshold + edge-rule
  property.
- **Batching is necessary but not sufficient.** The graph signal exists
  (`counterparty_overlap`) but is drowned by an over-connected `cluster_size` at
  a permissive threshold.
- **Concrete, ranked fixes** (all scoring-logic changes — out of Week 11 scope):
  1. `CLUSTER_MIN_SIGNALS: 1 → 2` — smallest lever. **Tested** — see below.
  2. Rare-counterparty edge filtering so `cluster_size` stops over-connecting.
  3. Cluster-aligned batching (group by campaign/time/referrer, not at random).

## Update — the `CLUSTER_MIN_SIGNALS` 1→2 experiment ([details](threshold-experiment.md))

The fix #1 hypothesis was tested rigorously (single variable, red lines,
ablation). Result: **partial improvement, gap not closed.**

- Balanced accuracy **54.2% → 62.5%** (+8.3 pts), by cutting human
  false-positives 8/12 → 5/12 — exactly the predicted mechanism.
- Held-out TEST accuracy **unchanged** (82.1% this run — note: baseline drifted
  up from the documented 78.6% by one wallet, live-data). No regression there.
- Tradeoffs: balanced sybil recall 75% → 67% (one fewer sybil caught), and the
  sybil-heavy TRAIN split dropped 5.2 pts.

So batch + this one threshold change lifts balanced accuracy a real but modest
amount and does **not** restore cluster-aware accuracy. Fixes #2 and #3 remain
the path to actually closing the gap.

**Shipped (2026-08-10).** This is now the **default** scoring behavior:
`CLUSTER_MIN_SIGNALS = 2` under `SCORER_VERSION = 0.5.0-threshold-v2`. So the
numbers above (balanced 62.5%, human FP 5/12, sybil recall 67%) are current
production reality, not an experiment. Old `0.4.0-graph` behavior is still
reproducible with `SCORING_CLUSTER_MIN_SIGNALS=1`. Remaining work to actually
close the gap: [scoring-v2-proposal.md](scoring-v2-proposal.md) (#2–4).

## Reproduce

```bash
RATE_LIMIT_PER_MINUTE=5000 docker compose up -d api      # needs a real ETHERSCAN_API_KEY
# then run the 24-wallet single-vs-batch comparison (scratch script in the PR notes),
# or by hand: POST /verify per wallet, then one POST /verify/batch of all 24.
```

Numbers vary slightly with live on-chain data; the pattern (batch ≈ single on a
balanced set, everyone → bronze) is stable.
