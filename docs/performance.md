# Performance & optimization (Week 12)

Local profiling + a basic load benchmark, with an honest split between "fine for
the demo" and "would need work for production." No deployment here.

## Setup

- Single-node docker-compose (api + Postgres + Redis), MacBook, no tuning.
- Rate limit raised for the run (`RATE_LIMIT_PER_MINUTE=1000000`) so the limiter
  isn't the bottleneck under test.
- Wallets already ingested (features cached in Postgres), so no Etherscan calls
  during the benchmark — this measures the API's own compute/IO, not the
  provider.

## Response caching (`/verify`)

Short-TTL Redis cache of the **assessment** (score), not the proof — a hit skips
feature-resolve + scoring but still mints a fresh, uniquely nonced proof.
`cache_hit` is exposed via the `X-Cache: HIT|MISS` header (no JSON contract
change). Best-effort: a Redis outage degrades to a miss. Keyed by
`SCORER_VERSION` so a scorer bump auto-invalidates.

## Load benchmark — `/verify` (open-loop, hot wallet, cache warm)

| target rps | achieved | errors | cache hits | p50 | p95 | p99 |
| --- | --- | --- | --- | --- | --- | --- |
| 10 | 10.2 | 0 | 50/50 | 10.5 ms | 11.5 ms | 37.8 ms |
| 50 | 50.1 | 0 | 250/250 | 6.7 ms | 8.0 ms | 14.8 ms |
| 100 | 100.1 | 0 | 500/500 | 6.4 ms | 7.7 ms | 17.1 ms |

**Verdict: `/verify` is production-shaped for the demo's scale.** It holds 100
rps with zero errors and single-digit-ms p50. Honest caveat: with all requests
on one hot wallet the cache hit-rate is 100%, so this measures the *cached*
path. The cache's real-world win is modest on small data — the underlying
feature lookup is already **0.1 ms** (index-backed, see below) — so the ~6 ms
p50 is dominated by proof signing + the per-request history write + HTTP, not by
work the cache removed. Caching matters most for **cold** wallets (skips a
would-be ingestion) and under DB contention, not for warm reads on a small DB.

## Load benchmark — `/verify/batch` (5 concurrent clients × 20-wallet batches)

| concurrency | batch size | total | errors | throughput | p50 | p95 |
| --- | --- | --- | --- | --- | --- | --- |
| 5 | 20 | 15 | 0 | 0.9 batches/s (~18 wallets/s) | **5.3 s** | 5.6 s |

**Verdict: the batch path is the bottleneck — acceptable for the demo, NOT for
production as-is.** A single 20-wallet batch takes ~5.3 s under 5-way
concurrency (0 errors — it's slow, not failing). Why, concretely:

1. **20 separate commits per batch.** `score_batch_with_graph` calls
   `record_score` per wallet, and each `record_score` **commits**. That's 20
   round-trip commits/batch × 5 concurrent = ~100 competing commits on one
   Postgres. This dominates.
2. **Per-wallet feature aggregation.** `compute_features` runs aggregation
   queries over `wallet_transactions` (33k rows here) once per wallet — 20× per
   batch.
3. **O(N²) graph pass.** `compute_graph_features` does pairwise
   counterparty-overlap + adjacency — 400 comparisons at N=20, bounded by the
   100-wallet cap (≤10k). Real but not the dominant cost here.

**Acceptable for the demo** because the batch is a *background* job (the hybrid
re-score runs every ~15 min over recent signups), not a real-time path — even
100 wallets ≈ 5 batches ≈ ~25 s, once every 15 min, is fine.

**For production it needs:** (a) **one transaction per batch** instead of 20
commits (biggest lever); (b) a single set-based feature query for the cohort
instead of 20 per-wallet queries; (c) a bounded worker pool / queue rather than
naive concurrent batches hitting one DB; (d) parallel, pooled ingestion for cold
batches (currently sequential per wallet). The O(N²) graph is fine within the
≤100 cap; do not raise the cap without revisiting it.

## DB index review

Profiled the hot queries with `EXPLAIN ANALYZE`. Every hot-path lookup is
already index-backed (`ix_wallets_address`, `ix_wallet_features_wallet_id`,
`ix_trust_score_history_wallet_id`, the unique constraints, etc.). On the current
small data Postgres often chooses a **seq scan** because the tables are tiny —
that is the correct plan, and everything is sub-millisecond:

- `/verify` feature lookup (join wallets on address): **0.109 ms**.
- dashboard `usage_events` 24h window: **0.575 ms** (seq scan of 218 rows).

**No migration added** — profiling shows no current need (per the Week-12 rule).

**Production-scale note (documented, not fixed):** `usage_events` has no index on
`created_at`, so the dashboard's time-window aggregations seq-scan. Harmless at
218 rows / <1 ms; at millions of usage rows this would need an index on
`usage_events.created_at` (or a BRIN index). Add it when the table grows, with a
migration, after confirming the plan flips to an index scan.

## Summary

- `/verify`: fast and stable (100 rps, single-digit-ms p50, 0 errors). Ship-ready
  for the demo.
- `/verify/batch`: correct but heavy (~5 s/20-wallet batch under load) — fine as
  a background job, needs the batching/transaction work above before high-volume
  production use.
- Indexes: adequate; one production-scale index deferred with a clear trigger.
