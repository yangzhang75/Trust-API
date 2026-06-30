# Blockchain Data Ingestion (Week 2)

The ingestion service fetches a wallet's on-chain transaction history from a
Web3 data provider, normalizes it, and persists it to Postgres through an
idempotent ETL pipeline driven by a background worker.

> Scope: **Ethereum only** this week, but the provider/registry is built so
> additional chains (Polygon, Solana) plug in later. The `/verify` contract
> is unchanged — features/scoring/proof remain stubs; ingestion feeds future
> weeks via the `wallet_transactions` table, never the public API.

## Provider choice — Etherscan (V2 unified API)

We use **Etherscan's V2 API** (`account` / `txlist`) rather than Alchemy:

- A single REST call returns a wallet's full normal-transaction list with
  exactly the fields we normalize — `hash`, `timeStamp`, `from`, `to`,
  `value`, `blockNumber` — with simple pagination.
- **One API key works across chains** via the `chainid` parameter, so adding
  Polygon/etc. later is just another entry in the chain-id registry.
- Generous free tier; no need to stitch separate incoming/outgoing transfer
  queries (as Alchemy's `getAssetTransfers` requires) or a second metadata
  call for timestamps.

The key is read from `ETHERSCAN_API_KEY` (env only — never committed). With
no key set, live ingestion is disabled: the API still runs and the
worker/seed register wallet rows without transaction history.

## ETL pipeline

```
            Extract                Transform                 Load
 Etherscan ─────────▶ provider ──▶ normalize_transactions ─▶ load_transactions ─▶ Postgres
 account/txlist       (resilient)   raw rows → Transaction     idempotent upsert    wallet_transactions
                          │                                                          + wallet aggregates
                      Redis cache (per wallet+chain, TTL)
```

- **Extract** — `services/ingestion/provider.py::EtherscanClient`. Every call
  has a timeout; transient failures (timeout, HTTP 429/5xx, provider
  rate-limit messages) are retried with exponential backoff (tenacity) and,
  if still failing, raised as `DataUnavailableError`. Non-recoverable issues
  (e.g. bad key) raise `ProviderError`. `fetch_wallet_history` adds a Redis
  cache so a wallet isn't re-fetched on every call.
- **Transform** — `services/ingestion/transform.py::normalize_transactions`.
  Pure function: maps raw rows to `Transaction` (tx hash, block number, block
  time, value in wei, direction `in|out|self`, counterparty). Malformed or
  unrelated rows are skipped, not fatal.
- **Load** — `services/ingestion/load.py::load_transactions`. Upserts with
  `ON CONFLICT (wallet_id, tx_hash) DO NOTHING`, so re-ingesting the same
  wallet creates **no duplicates**. Recomputes wallet `first_seen`,
  `last_seen`, and `tx_count`.

Errors are typed (`services/ingestion/errors.py`) so callers/the API can map
them sanely (e.g. 503) instead of 500-ing.

## Data model

`wallet_transactions` (internal storage — never exposed by the public API):

| column | type | notes |
| --- | --- | --- |
| `id` | int PK | |
| `wallet_id` | FK → `wallets.id` | cascade delete, indexed |
| `chain` | str(32) | e.g. `ethereum` |
| `tx_hash` | str(66) | unique per wallet (idempotency) |
| `block_number` | bigint | |
| `block_time` | timestamptz | |
| `value_wei` | numeric(80,0) | full uint256 range |
| `direction` | str(8) | `in` / `out` / `self` |
| `counterparty` | str(64) | the other address |
| `created_at` | timestamptz | |

Unique constraint: `uq_wallet_tx_hash (wallet_id, tx_hash)`.

New `wallets` columns: `first_seen`, `last_seen`, `tx_count` (ingestion
aggregates). Migration: `0002_wallet_transactions`.

## Running it

```bash
# 1. migrate
make migrate                         # alembic upgrade head

# 2. set a provider key (optional; without it, wallets register w/o history)
export ETHERSCAN_API_KEY=...         # never commit this

# 3. seed the labeled sample wallets
make seed                            # python scripts/seed_wallets.py

# 4. ingest / refresh
make worker                          # one pass (python -m trust_api.worker --once)
python -m trust_api.worker --wallet 0xd8dA...   # ad-hoc single wallet
python -m trust_api.worker                      # scheduled (interval) mode
```

Under docker-compose the `worker` service runs the scheduler automatically;
pass `ETHERSCAN_API_KEY` via your environment/`.env`.

## Sample dataset

`data/labeled_wallets.json` holds a small labeled set used here and for Week
4 scoring validation. Human entries are well-known public addresses; the
Sybil/bot entries are **illustrative/synthetic placeholders** (see
`label_basis`) — not accusations against real addresses — to be replaced with
a verified labeled set (e.g. from a public airdrop Sybil post-mortem) before
scoring work begins.
