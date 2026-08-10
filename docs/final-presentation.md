# Proof-of-Human Trust API — final presentation (living draft)

> Status: draft. Weeks 1–11 complete; Week 12 (deployment + performance) in
> progress. The accuracy section below is final and honest — it is a
> **"problem discovered and diagnosed"** story, not a "problem solved" one.

## What was built (Weeks 1–11)

- **Scoring** — transparent, rule-based (no ML), graph/cluster features, verified
  Sybil labels + an evaluation harness (`scoring-eval.md`).
- **Proof** — real Ed25519 signed, expiring, revocable attestations; offline
  verification with only the public key (`proof.md`, `proof-flow.md`).
- **Verification flow** — `/proof/generate`, `/proof/verify` (raw or compact),
  a runnable end-to-end demo.
- **Dashboard** — internal Streamlit monitoring over the same Postgres + Redis.
- **Integration simulation** — a mock client consuming the API over real HTTP
  across three scenarios (`integration-demo.md`).
- **Hybrid batch** — `/verify/batch` + the register-instantly / re-score-in-batch
  pattern (`hybrid-integration.md`).

Every capability is real (live on-chain data), 100% test coverage, CI green.

## The honest centerpiece: the accuracy gap

This is the part I'm most proud of — not because we won, but because we found
and diagnosed a real problem instead of hiding it.

**What we found (Week 10).** Consuming the API one wallet at a time,
single-`/verify` accuracy on a balanced 12-human/12-sybil set was **~54%** — far
below the **78.6%** cluster-aware headline. Cause: graph/cluster features can't
be computed from a single wallet.

**What we tried (Week 11).** Built `/verify/batch` so graph features are computed
across the batch. Measured honestly: batch scored **54.2%** on the same balanced
set — **no improvement**. Graph features populated, but the `sybil_cluster` flag
fired on *everyone* (humans 12/12), because an arbitrary batch over-connects
(shared mainstream counterparties) and `CLUSTER_MIN_SIGNALS = 1` let that one
corrupted signal trip the flag. The genuinely discriminating feature
(`counterparty_overlap`, 0.47 sybil vs 0.10 human) was drowned out.
(`accuracy-gap.md`.)

**What we proved (threshold experiment).** A single-variable, red-lined,
ablated experiment — `CLUSTER_MIN_SIGNALS: 1 → 2` — lifted balanced accuracy
**54.2% → 62.5%** (+8.3 pts) by cutting human false-positives 8/12 → 5/12, with
**no held-out-test regression**, at the cost of one fewer sybil caught and a
5.2-pt drop on the sybil-heavy train split. (`threshold-experiment.md`.)

**Honest bottom line:** the gap is **partially narrowed, not closed.** 62.5% is
still far from 78.6%, and part of that 78.6% is a class-imbalance artifact. Fully
closing it needs scoring-logic work we scoped but did **not** implement:
rare-counterparty edge filtering, cluster-aligned batching, and re-tuning on a
balanced holdout (`scoring-v2-proposal.md`).

**Why this is the highlight:** at every step the measurement drove the claim —
we reproduced the gap, diagnosed it to a specific line (`CLUSTER_MIN_SIGNALS`),
tested one variable with pre-set red lines and an ablation, and reported the
modest result and its tradeoffs without inflation. No "gap closed."

## Deployment & performance (Week 12 — in progress)

_To be completed: containerized deployment, migration/runbook, load/latency
profile, and the honest performance notes (e.g. the O(N²) graph pass and
N-ingest cost in `hybrid-integration.md`)._
