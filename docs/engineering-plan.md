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

## Week 2 — Ingestion (real on-chain data) ✅
- Real Ethereum ingestion via Etherscan V2 (`account/txlist`); chain-id
  registry so Polygon/Solana plug in later (Ethereum only this week).
- Resilient client: timeouts, exponential-backoff retry, 429 handling,
  typed errors; Redis caching of fetched history.
- Idempotent ETL (transform → upsert) into `wallet_transactions`; background
  worker; labeled sample dataset + seed script. See `docs/ingestion.md`.
- Deferred to a later week: Solana/Polygon adapters, multi-provider failover.

## Week 3 — Feature Engineering ✅
- 10 real per-wallet behavioral features (age, activity intensity,
  counterparty diversity, inbound ratio, burst score, dormancy, recency)
  computed from `wallet_transactions` via SQL aggregation.
- Persisted to `wallet_features` (idempotent upsert); batch job +
  worker wiring; stub-safe read into /verify. See `docs/features.md`.
- Deferred to later weeks: gas profiles, funding-source lineage,
  feature versioning/backfill.

## Week 4 — Trust Scoring Engine ✅
- Real, transparent, rule-based scoring (no ML): weighted positive
  evidence minus risk-flag penalties, all tunable in scoring/config.py.
- Wired into /verify (contract unchanged; features ingested/computed on
  demand). Verified Sybil labels + evaluation harness → docs/scoring-eval.md
  (83% accuracy, honest limitations). See docs/scoring.md.
- Deferred: ML ensemble, funding-cluster Sybil detection, trust_scores
  persistence, L2 ingestion for L2-native wallets.

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
