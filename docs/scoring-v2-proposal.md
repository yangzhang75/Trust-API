# Scoring v2 proposal — closing the balanced-accuracy gap

**Status:** proposal. Motivated by [`accuracy-gap.md`](accuracy-gap.md) and the
validated experiment in [`threshold-experiment.md`](threshold-experiment.md).
All items are scoring-logic changes (thresholds/rules), deliberately kept out of
Weeks 11–12 and gathered here for a dedicated scoring pass.

## Problem (recap)

On a **balanced** 12-human/12-sybil set, both single `/verify` and
`/verify/batch` score ~54% — far below the 78.6% cluster-aware headline. Precise
cause: the graph `sybil_cluster` flag fires on **everyone** (humans 12/12)
because the `cluster_size` signal is corrupted by over-connection (arbitrary
cohorts share mainstream counterparties → one giant component), and
`CLUSTER_MIN_SIGNALS = 1` lets that single always-true signal trip the flag. The
one genuinely discriminating feature, `counterparty_overlap` (0.47 sybil vs 0.10
human), is drowned out.

## Fix 1 — `CLUSTER_MIN_SIGNALS: 1 → 2`  ✅ validated (partial)

Require two graph signals so `cluster_size` alone can't trip the flag.

- **Measured:** balanced 54.2% → 62.5% (+8.3 pts); human false-positives
  8/12 → 5/12; held-out TEST unchanged; sybil recall 75% → 67%; TRAIN −5.2 pts.
- **Verdict:** real but modest; **narrows, does not close** the gap. Low-risk
  (no held-out-test regression).
- **To ship:** flip the `SCORING_CLUSTER_MIN_SIGNALS` default to `2`, bump
  `SCORER_VERSION` (history rows stay distinguishable), and update the scoring
  tests that assert threshold-1 behavior. Not done yet — a deliberate decision.

## Fix 2 — rare-counterparty edge filtering  (not implemented)

Root-cause fix for over-connection. In `graph.py`, an edge between two wallets
currently forms if they share **any** counterparty. Change: only count a shared
counterparty (or funder) as an edge if that address is **low-degree** across the
cohort (a plausible farming funder), ignoring high-degree mainstream addresses
(major DEXs, stablecoins, bridges). Then `cluster_size` reflects real farming
structure instead of "everyone used Uniswap," and it becomes discriminating on
its own. Expected to help more than Fix 1, and to make Fix 1 less load-bearing.

## Fix 3 — cluster-aligned batching  (product/integration, not scoring)

Graph features only discriminate on a meaningful neighborhood. Batch wallets
that plausibly belong together (same campaign / referrer / signup time window),
not a random mix, so `/verify/batch` sees real structure. This is a client-side
batching policy (see [`hybrid-integration.md`](hybrid-integration.md)), not a
scoring change.

## Fix 4 — grow + balance the labeled set, re-evaluate on a balanced holdout

The 78.6% headline is **Sybil-dominated** (`scoring-eval.md`'s own caveat), which
inflates it relative to real-world balanced performance. Add independent human +
sybil clusters from more projects, and report a **balanced** held-out accuracy as
the headline so tuning targets real discrimination, not the class prior.

## Suggested order

1. Fix 2 (biggest lever, root cause) → re-measure balanced + holdout.
2. Re-evaluate Fix 1's threshold *after* Fix 2 (it may no longer be needed, or
   the right value may differ — re-tune only against a balanced holdout).
3. Fix 4 (data) in parallel, to make every number above trustworthy.
4. Fix 3 on the integration side, independent of the above.

Each change must be measured single-variable with red lines and an ablation, as
in `threshold-experiment.md` — no multi-knob tuning to chase a number.
