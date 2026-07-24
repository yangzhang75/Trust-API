# Architecture

The Proof-of-Human Trust API is a B2B Reputation-as-a-Service product: a
consumer sends a wallet address, and we return a human-likelihood
assessment, a trust tier, a confidence score, risk flags, and a
time-bounded signed proof.

For who calls this and why, see [`api-use-cases.md`](api-use-cases.md).

> **Status (through Week 6):** the full request path runs end-to-end on
> **real** components — multi-chain ingestion (Week 2/4), behavioral
> features (Week 3), a transparent rule-based scorer (Week 4), an operable
> pipeline with history + metrics (Week 5), and **real Ed25519-signed,
> revocable proofs** (Week 6). Each stage was built behind the typed
> interfaces fixed in Week 1.

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
   │ingestion/  │   │features/   │   │scoring/    │   │ proof/     │
   └────────────┘   └────────────┘   └────────────┘   └────────────┘
        normalize        derive          assess           attest
       activity         features      tier/likelihood    sign + expire
                                      + risk flags
                                      │
                                      ▼
                            ┌───────────────────┐
                            │     Trust API     │   FastAPI app
                            │  POST /verify           │   (api/routes.py)
                            │  POST /proof/generate   │
                            │  POST /proof/verify     │
                            │  GET  /proof/public-key │
                            │  GET  /health           │
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

1. **Ingestion** (`services/ingestion/`) — **real, multi-chain (Week 2 +
   Week 4 L2):** fetches and normalizes on-chain transactions via the
   Etherscan V2 API across **Ethereum and Arbitrum** (one key, `chainid`
   registry), idempotently upserting to `wallet_transactions`. See
   [`ingestion.md`](ingestion.md).
2. **Features** (`services/features/`) — **real (Week 3):** computes 10
   per-wallet behavioral features from `wallet_transactions` via SQL
   aggregation and upserts them into `wallet_features`. Driven by a batch
   job / the worker after ingestion. See [`features.md`](features.md).
3. **Scoring** (`services/scoring/`) — **real (Week 4):** a transparent,
   deterministic rule engine maps features to `human_likelihood`,
   `trust_tier`, `confidence_score`, and `risk_flags`. All weights and
   thresholds live in `scoring/config.py`. No ML. See [`scoring.md`](scoring.md)
   and current results in [`scoring-eval.md`](scoring-eval.md). /verify now
   returns real scores. *Persisting to `trust_scores` is a later week.*
4. **Proof** (`services/proof/`) — **real (Week 6):** issues a
   time-bounded, privacy-preserving **Ed25519-signed** attestation over a
   canonical form of the assessment (`keys.py` signing, `canonical.py`
   serialization, `service.py` generate/verify). A third party verifies it
   offline with only the public key (`GET /proof/public-key`); no raw tx
   data is in the payload. Proofs are persisted to `proofs` (jsonb only) so
   they can be revoked before expiry (`python -m trust_api.jobs.revoke`,
   `POST /proof/verify`). See [`proof.md`](proof.md).

   **Proof-verification flow (Week 9):** the proof capability is exposed as a
   full user journey — Wallet → Generate → Share → Verify.
   - `POST /proof/generate` returns a **self-contained** proof (`payload`,
     `signature`, a compact `encoded` base64url form, and a human `summary`)
     that can be shared as-is.
   - `share.py` provides the two interchangeable wire forms (raw canonical
     JSON and compact base64url) with a deterministic round-trip, plus
     `decode_proof`.
   - `offline.py` `verify_offline(public_key, proof)` is the public-key-only
     verification path (no server, no DB); `service.py verify` now **delegates**
     to it and only layers revocation, so the server and offline paths run the
     same checks.
   - `POST /proof/verify` accepts a proof in either form and returns
     `{valid, reason, key_id, expires_at, revoked, summary}`. It keeps API-key
     auth (abuse/DoS protection); the open, no-auth path is offline verification.
   - `python -m trust_api.demo.proof_flow` walks the whole journey and every
     failure mode. See [`proof-flow.md`](proof-flow.md) — the single integration
     doc for third-party developers.

**Pipeline (Week 5):** `pipeline.py` chains ingest → features → score →
persist as one operable, scheduled stage — per-wallet failure isolation,
append-only `trust_score_history` (per `scorer_version`), structured JSON
logs, and counters at `/metrics`. Run via `python -m trust_api.jobs.score`
or the background worker. See [`pipeline.md`](pipeline.md).

**Monitoring dashboard (Week 8):** a **separate Streamlit service**
(`dashboard/streamlit_app.py`) — NOT part of the FastAPI app — reads the same
Postgres + Redis to show system health, throughput, score distributions, risk
flags, per-key usage, and a wallet inspector. Its tested data layer lives in
`trust_api/dashboard/` (no streamlit import); the UI is a thin render on top.
Access reuses the API-key mechanism (a `DASHBOARD_API_KEYS` admin tier or any
`API_KEYS` entry). Runs as its own `dashboard` compose service on `:8501` from
`Dockerfile.dashboard`. See [`dashboard.md`](dashboard.md).

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
- **Redis 7** backs rate limiting, the ingestion cache, and the shared
  cross-process scoring metrics (Week 6 H1 fix).
- The **monitoring dashboard** (Week 8) is a read-only consumer of these
  tables + the Redis metrics; it never writes.

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
- **Deterministic scoring.** The rule engine is a pure function of the
  wallet's features (no ML, no randomness), so scores are reproducible and
  auditable. Proof `nonce`/`issued_at` are the only per-call variation.
- **Privacy by construction.** Raw transaction data never leaves
  ingestion; only aggregated features and attestations are persisted.
