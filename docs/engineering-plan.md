# Engineering Plan — 12-Week Roadmap

A B2B Reputation-as-a-Service API that scores how likely a wallet is
operated by a real human, with a verifiable proof. The roadmap moves from
skeleton/contracts → real data → real scoring → hardening → launch.

Each week builds on stable interfaces defined earlier, so later work fills
in stubbed bodies without breaking the API contract.

## Week 1 — Architecture & System Design ✅ (this week)
- Repo scaffold, tooling (ruff/black/pytest), CI.
- `POST /verify` + `GET /health` contracts with Pydantic v2 models/enums.
- Stubbed pipeline (ingestion → features → scoring → proof) returning
  deterministic data from a hash of the wallet.
- API-key auth + Redis rate limiting.
- DB schema (SQLAlchemy + one Alembic migration), docker-compose, docs.

## Week 2 — Ingestion (real on-chain data)
- Real EVM ingestion via RPC providers/indexers (Alchemy/Etherscan/node).
- Per-chain adapters; add **Solana** support and wallet-format validation.
- Redis caching of fetched activity; backoff/retry; provider failover.

## Week 3 — Feature Engineering
- Real features: account age, tx cadence, gas profiles,
  counterparty-graph diversity, funding-source lineage.
- Persist to `wallet_features`; feature versioning and backfill jobs.

## Week 4 — Scoring & Sybil Detection
- Replace stub scoring with a calibrated heuristic/ML ensemble.
- Dedicated Sybil-clustering stage; populate real `risk_flags`.
- Score persistence (`trust_scores`) and explainability metadata.

## Week 5 — Proof Issuance & Verification
- Real signing (Ed25519/secp256k1) with keys in KMS/HSM.
- Public verification endpoint/library; proof revocation & expiry policy.

## Week 6 — API Key Management & Multi-Tenancy
- Self-serve key issuance; store hashes in `api_keys`; scopes & quotas.
- Per-tenant rate limits and usage metering via `usage_events`.

## Week 7 — Persistence, Caching & Performance
- Read/write paths optimized; connection pooling; query tuning.
- Tiered caching (Redis) for hot wallets; idempotency keys.

## Week 8 — Observability
- Structured logging, request IDs, metrics (Prometheus), tracing (OTel).
- Dashboards and alerting; SLOs for latency and availability.

## Week 9 — Security Hardening
- Threat model; input fuzzing; secrets management; dependency scanning.
- Decide rate-limit fail-open vs fail-closed per route; abuse controls.

## Week 10 — Reliability & Scale
- Horizontal scaling, graceful shutdown, DB migrations strategy.
- Load testing; queue-backed async ingestion for heavy wallets.

## Week 11 — Billing & Productization
- Usage-based billing on `usage_events`; plans/tiers; webhooks.
- Customer dashboard; API docs portal; SDKs.

## Week 12 — Launch Readiness
- End-to-end QA, security review, runbooks, on-call.
- Staging → production cutover; post-launch monitoring.

## Cross-cutting (all weeks)
- Keep the OpenAPI contract stable; version breaking changes.
- ≥80% test coverage; green CI on every PR.
- Privacy by construction: raw tx data never persisted.
