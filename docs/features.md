# Behavioral Features (Week 3)

The feature pipeline turns the raw `wallet_transactions` stored in Week 2
into **10 per-wallet behavioral features** that the scoring engine
consumes. Features are computed **only from data already in the database**
(`wallet_transactions` + `wallets`) — no provider calls — using SQL
aggregation (`COUNT`, `COUNT DISTINCT`, `MIN`/`MAX`, `FILTER`,
`date_trunc`) so large wallets are never pulled into Python.

> **Multi-chain (Week 4 reinforcement):** the aggregation query filters by
> `wallet_id` only — **not** by chain — so features aggregate across **all
> ingested chains** for a wallet (currently Ethereum + Arbitrum). This
> matters: a wallet that is quiet on Ethereum mainnet but active on
> Arbitrum now shows its real activity. Ingest every chain a wallet uses
> before computing features (the eval's `prepare_wallet` does this).

- **Code:** `src/trust_api/services/features/service.py`
- **Storage:** `wallet_features` table (one row per wallet+chain, upserted
  idempotently on `(wallet_id, chain)`)
- **Run:** `make features` / `python -m trust_api.jobs.compute_features`
  (the worker also refreshes features right after ingestion)
- **Determinism:** all time-relative features take a reference `now`
  (injected in tests); everything else is a pure function of stored data.

## The 10 features

| # | Feature | Formula | Unit | Captures |
|---|---------|---------|------|----------|
| 1 | `wallet_age_days` | `(now − first_tx_time).days` | days | How long the wallet has been active; brand-new wallets are riskier. |
| 2 | `tx_count` | `COUNT(*)` | count | Overall transaction volume. |
| 3 | `active_days` | `COUNT(DISTINCT date(block_time))` | days | On how many distinct calendar days the wallet transacted. |
| 4 | `tx_per_active_day` | `tx_count / active_days` | ratio | Activity intensity; very high values suggest automation. |
| 5 | `counterparty_count` | `COUNT(DISTINCT counterparty)` | count | Breadth of distinct addresses interacted with. |
| 6 | `counterparty_diversity_ratio` | `counterparty_count / tx_count` | ratio 0–1 | Diversity of interactions; low = repetitive/bot-like. |
| 7 | `inbound_ratio` | `inbound_tx / tx_count` | ratio 0–1 | Share of incoming transfers; extreme skew can flag funnels/sinks. |
| 8 | `burst_score` | `MAX(tx per 1-hour window)` | count | Peak transactions in any single hour — a proxy for bot bursts. |
| 9 | `dormancy_flag` | `recency_days > 90` | boolean | Whether the wallet has been inactive for more than 90 days. |
| 10 | `recency_days` | `(now − last_tx_time).days` | days | Days since the wallet's most recent transaction. |

## Graph / cluster features (Week 4 "B")

These describe how a wallet relates to *other in-sample wallets* through the
funding + counterparty graph (transductive — computed over the labeled/
evaluated set in a batch pass; in production, "in-sample" = a wallet's
ingested neighborhood). Code: `services/features/graph.py`.

| # | Feature | Formula / definition | Captures |
| --- | --- | --- | --- |
| 11 | `shared_funder_score` | fraction of my top-3 funders also used by ≥1 other in-sample wallet (0–1) | coordinated funding of a cluster (e.g. Safe farms) |
| 12 | `counterparty_overlap_score` | max Jaccard overlap of my counterparty set with any other in-sample wallet (0–1) | wallets hitting the same contracts/peers |
| 13 | `funding_chain_depth` | longest chain of in-sample funders ending at me (0 = funded externally) | relay / sequential-transfer farming chains (e.g. Hop) |
| 14 | `cluster_size_estimate` | size of my connected component in the shared-funder / shared-counterparty / direct-transfer graph | overall cluster membership |

Different projects show different edge types (Hop = mutual transfers, Safe =
shared funder), so these four features are complementary. Their effect on
the score is measured by ablation in [`scoring-eval.md`](scoring-eval.md),
not assumed.

Notes:
- Ratios are rounded to 6 decimal places; division guards return `0.0` when
  the denominator is `0` (e.g. a wallet with no transactions).
- Graph features are `0` for a lone wallet (e.g. a single `/verify` call
  with no ingested neighborhood), so they never penalize an isolated lookup.
- Dates and hour windows are computed in **UTC** (`timezone('UTC', ...)`)
  for stable, timezone-independent results.
- A wallet with no stored transactions yields all zeros / `dormancy_flag =
  false`.
- These are **privacy-preserving aggregates** — raw transaction rows stay
  internal and are never exposed by the public API.

## Idempotency

`compute_features` upserts on `(wallet_id, chain)`, so re-running the job
updates the single existing row rather than creating duplicates. Batch runs
(`compute_features_for_wallets`) isolate per-wallet failures: one wallet
erroring is logged and rolled back without aborting the rest.
