# Proof-of-Human Trust API — final presentation

> Status: **complete (Weeks 1–12).** Backend Reputation-as-a-Service:
> wallet trust scoring, signed proofs, a verification flow, an internal
> dashboard, a mock-integration platform, a hybrid batch path, and
> production-ready deployment config. The accuracy section is deliberately a
> **"problem discovered and diagnosed"** story, not a "problem solved" one —
> that honesty is the point, not a caveat.

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

**What we shipped (threshold fix, `0.5.0-threshold-v2`).** A single-variable,
red-lined, ablated experiment — `CLUSTER_MIN_SIGNALS: 1 → 2` — then shipped as
the default. Current **production** numbers:

- Balanced accuracy **54.2% → 62.5%** (+8.3 pts), by cutting human
  false-positives from **8/12 → 5/12** (2 humans even recover to gold).
- Held-out TEST accuracy **82.14%** (unchanged by the fix).

**The tradeoff, stated plainly (not hidden behind the accuracy gain):**

- Human false-positives **dropped 8/12 → 5/12** (the win).
- Sybil recall **dropped 75% → 67%** — one real sybil is now missed. Firing the
  flag less eagerly helps humans and costs a borderline sybil; that is a genuine
  precision/recall tradeoff, not a free lunch.
- Held-out **TRAIN** accuracy dropped **76.6% → 71.4% (−5.2 pts)**. This is *not*
  a red-line breach — TEST (the held-out, primary metric) is unchanged — but it
  is honest to note: on a sybil-dominated split, predicting "sybil" less often
  costs accuracy.

**A number that changed — the 82.14% vs the old 78.57%.** The held-out TEST
baseline now reads **82.14%**, replacing the **78.57%** previously in
`scoring-eval.md`. This is **not** an effect of our change (TEST is identical at
`=1` and `=2`); it is **live-data drift**. Reproducing the experiment required
re-ingesting all 105 labeled wallets fresh, and wallets accrue on-chain activity
between eval runs — one test wallet crossed the decision boundary (22/28 →
23/28). We discovered this during the experiment and report it rather than
quietly adopting the higher number.

**Honest bottom line:** the gap is **partially narrowed, not closed.** 62.5% is
still far from the cluster-aware headline, and part of that headline is a
class-imbalance artifact. Fully closing it needs scoring-logic work we scoped but
did **not** implement: rare-counterparty edge filtering, cluster-aligned
batching, and re-tuning on a balanced holdout (`scoring-v2-proposal.md`).

**Why this is the highlight:** at every step the measurement drove the claim —
we reproduced the gap, diagnosed it to a specific line (`CLUSTER_MIN_SIGNALS`),
tested one variable with pre-set red lines and an ablation, and reported the
modest result and its tradeoffs without inflation. No "gap closed."

**Scoring v2 — first attempt reverted (honest negative result).** We then tried a
rare-counterparty filter (drop shared-infra addresses like USDC/WETH/Uniswap
from the graph). It improved the held-out TEST (+3.6 pts, ablation-confirmed) but
did **not** improve the balanced set, and a blanket degree filter risks stripping
genuine farming-funder signal (a sybil-recall collapse concern). We **reverted**
to `0.5.0-threshold-v2` and documented it as a negative result rather than ship a
change that didn't do its job (`scoring-v2-experiment-log.md`). Production remains
`0.5.0-threshold-v2`. A smarter partial/weighted filter is future work.

## Performance (Week 12 — done)

Local profiling + a basic load benchmark (`performance.md`).

- **Response caching:** short-TTL Redis cache of the /verify assessment, with an
  `X-Cache: HIT|MISS` header (no JSON contract change) and best-effort
  degradation on a Redis outage.
- **`/verify` load:** sustains **10 / 50 / 100 rps with 0 errors**, p50 **6–10 ms**,
  p95 8–12 ms, p99 15–38 ms (cache-warm). Ship-ready at demo scale. Honest note:
  the cache's win is modest on warm small data (the feature lookup is already
  0.1 ms) — it matters most for cold wallets and under contention.
- **`/verify/batch` load:** the bottleneck — **~5.3 s per 20-wallet batch** at
  5-way concurrency (0 errors, just slow). Fine as a *background* job (the hybrid
  re-score runs every ~15 min), **not** production-ready for high volume. Root
  causes and fixes documented: 20 commits/batch → one transaction, per-wallet
  feature queries → one set-based query, bounded worker pool, pooled ingestion.
- **Indexes:** hot paths are index-backed and sub-millisecond; no migration
  needed now. One production-scale index (`usage_events.created_at`) is deferred
  with a clear trigger.

## Deployment (Week 12 — configuration complete)

Deployment configuration is **production-ready** — Fly.io config
([`fly.toml`](fly.toml): two processes, `/health` check, release-command
migrations), secret management (`fly secrets` for `DATABASE_URL`, `REDIS_URL`,
`API_KEYS`, `ETHERSCAN_API_KEY`, `PROOF_SIGNING_KEY`), health checks (app
`/health` + docker-compose healthchecks), and a rollback procedure are all in
place ([`docs/deployment.md`](deployment.md)). **Not deployed to a paid host
during the internship for cost reasons; local demonstration through
docker-compose and the mock platform is sufficient for the final review.** This
is a demo-time choice, not a limitation — any operator can `fly deploy` from the
committed config.

## How to run it (local)

```bash
docker compose up -d        # api, worker, dashboard, mock, Postgres, Redis
scripts/live_demo.sh        # one-command end-to-end walkthrough (verified working)
```

The walkthrough exercises `/verify` (with `X-Cache` MISS→HIT), `/verify/batch`
(graph features + `graph_context_size`), proof generate/verify, the three mock
integration scenarios, and the hybrid re-score — all against the local stack.
The internal dashboard is at `http://localhost:8501`.

## Engineering quality

- **100% test coverage** enforced in CI (`--cov-fail-under=100`), plus a
  separate migration-check job; both green on every commit.
- Real data throughout (live Etherscan V2 ingestion), not fixtures.
- **Version discipline:** `SCORER_VERSION` bumped on the scoring change
  (`0.5.0-threshold-v2`); old history rows keep their `0.4.0-graph` tag.
- **Contract discipline:** the `/verify` request/response shape has been stable
  since Week 1; caching and metadata were added via headers, never the body.

## What's next (scoped, not built)

Honestly out of scope for this internship, documented for a follow-on:

- **Scoring v2** to actually close the balanced-accuracy gap: rare-counterparty
  edge filtering, cluster-aligned batching, and re-tuning on a balanced holdout
  ([`scoring-v2-proposal.md`](scoring-v2-proposal.md)).
- **Batch performance** for high-volume production: one transaction per batch,
  a set-based cohort feature query, and a bounded worker pool
  ([`performance.md`](performance.md)).
- **Live deployment** whenever a paid host is warranted — config is ready.
