# Architecture

The Proof-of-Human Trust API is a B2B Reputation-as-a-Service product: a
consumer sends a wallet address, and we return a human-likelihood
assessment, a trust tier, a confidence score, risk flags, and a
time-bounded signed proof.

For who calls this and why, see [`api-use-cases.md`](api-use-cases.md).

> **Week 1 status:** the full request path runs end-to-end, but every
> pipeline stage returns **deterministic stub data derived from a hash of
> the wallet address**. Real blockchain ingestion, feature engineering,
> scoring/ML, Sybil detection, and cryptographic signing are stubbed
> behind typed interfaces and marked with `# TODO(week N)`.

## The pipeline

```
                ┌─────────────────────────────────────────────────────────┐
 Data sources   │  on-chain RPC / indexers, attestations, off-chain signals │
 (Week 2+)      └─────────────────────────────────────────────────────────┘
                                      │
                                      ▼
   ┌────────────┐   ┌────────────┐   ┌────────────┐   ┌────────────┐
   │ Ingestion  │──▶│  Features  │──▶│  Scoring   │──▶│   Proof    │
   │ services/  │   │ services/  │   │ services/  │   │ services/  │
   │ingestion.py│   │features.py │   │scoring.py  │   │ proof.py   │
   └────────────┘   └────────────┘   └────────────┘   └────────────┘
        normalize        derive          assess           attest
       activity         features      tier/likelihood    sign + expire
                                      + risk flags
                                      │
                                      ▼
                            ┌───────────────────┐
                            │     Trust API     │   FastAPI app
                            │  POST /verify     │   (api/routes.py)
                            │  GET  /health     │
                            └───────────────────┘
                                      │
                                      ▼
                            ┌───────────────────┐
                            │     Consumers     │   B2B API clients
                            └───────────────────┘

         Data layer (cross-cutting):  PostgreSQL 16   +   Redis 7
         - Postgres: wallets, wallet_features,        - Redis: rate-limit
           trust_scores, proofs (jsonb), api_keys,      counters; ingestion
           usage_events                                 caching (Week 2+)
```

### Stages

1. **Ingestion** (`services/ingestion.py`) — fetches and normalizes raw
   on-chain activity for the requested chains. Never stores raw
   transaction data downstream. *Week 1: synthetic activity from a sha256
   of the wallet.*
2. **Features** (`services/features.py`) — derives privacy-preserving,
   normalized features from activity. Persisted to `wallet_features`
   (jsonb). *Week 1: simple deterministic transforms.*
3. **Scoring** (`services/scoring.py`) — maps features to a
   `human_likelihood`, `trust_tier`, `confidence_score`, and `risk_flags`.
   Persisted to `trust_scores`. *Week 1: transparent weighted average +
   thresholds; no ML, no Sybil detection.*
4. **Proof** (`services/proof.py`) — issues a time-bounded attestation
   (`issued_at`, `expires_at`, `valid_for_hours`, `signature`). Persisted
   to `proofs` (jsonb payload only). *Week 1: deterministic stub
   signature — not cryptographically meaningful.*

### Cross-cutting concerns

- **Auth** — `X-API-Key` validated against a configured allowlist
  (`api/deps.py`). Production keys will be stored as hashes in `api_keys`.
- **Rate limiting** — fixed-window-per-minute counter in Redis, keyed by
  API key. Fails open if Redis is unavailable (revisited in Week 2).
- **Config** — all runtime config via environment / pydantic-settings
  (`config.py`).

## Data layer

- **PostgreSQL 16** is the system of record. Tables: `wallets`,
  `wallet_features`, `trust_scores`, `proofs`, `api_keys`, `usage_events`.
  Feature and proof payloads are `jsonb` and never contain raw tx data;
  `api_keys` stores `key_hash`, never plaintext.
- **Redis 7** backs rate limiting now and ingestion/scoring caches later.

## Request flow for `POST /verify`

1. Validate API key (`401` if missing/unknown).
2. Enforce rate limit (`429` if exceeded).
3. Parse/validate the body (`422` if malformed).
4. Validate the wallet as an EVM address (`400` if invalid).
5. Run ingestion → features → scoring → proof.
6. Return the assembled `VerifyResponse` (`200`).

## Design principles

- **Contracts before logic.** The API shape, schemas, DB schema, and
  service interfaces are fixed in Week 1; later weeks fill in the bodies
  without breaking consumers.
- **Deterministic stubs.** Stub outputs are a pure function of the wallet,
  so tests and demos are stable.
- **Privacy by construction.** Raw transaction data never leaves
  ingestion; only aggregated features and attestations are persisted.
