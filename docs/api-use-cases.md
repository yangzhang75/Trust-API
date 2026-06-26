# API Use Cases

Who calls the Proof-of-Human Trust API, what problem it solves for them,
and which fields of the `POST /verify` response they act on.

The product answers one question for a wallet address: **"how likely is a
real, unique human behind this, and how much should I trust it?"** —
returned as `human_likelihood`, `trust_tier`, `confidence_score`,
`risk_flags`, and a verifiable `proof`.

## Primary actor

**B2B integrators** — protocols, apps, and platforms that need a
reputation signal for a wallet without building on-chain analytics
themselves. They authenticate with an API key and call `POST /verify`.

## Use cases

### UC-1 — Airdrop / reward Sybil filtering
**Who:** token teams, growth/airdrop platforms.
**Need:** stop one human (or bot farm) from claiming many allocations.
**Flow:** before allocating, call `/verify` per wallet; exclude or
down-weight wallets with low `human_likelihood`, `bronze` `trust_tier`, or
`sybil_suspected` / `low_counterparty_diversity` in `risk_flags`.
**Acts on:** `human_likelihood`, `risk_flags`, `confidence_score`.

### UC-2 — Access / feature gating
**Who:** dapps, communities, gated mints, allowlists.
**Need:** admit only sufficiently trustworthy wallets.
**Flow:** require `trust_tier >= silver` (or a `confidence_score`
threshold) to unlock an action; deny or step-up otherwise.
**Acts on:** `trust_tier`, `confidence_score`.

### UC-3 — Risk-based transaction limits
**Who:** wallets, payment/onramp providers, DeFi front-ends.
**Need:** size limits / friction proportional to risk.
**Flow:** map `trust_tier` to limits (e.g. gold = high cap, bronze = low
cap + extra checks); surface `risk_flags` to the user or reviewer.
**Acts on:** `trust_tier`, `risk_flags`.

### UC-4 — Governance / voting weight
**Who:** DAOs.
**Need:** reduce vote-buying and Sybil voting.
**Flow:** weight or qualify votes by `trust_tier` / `human_likelihood`;
flag `sybil_suspected` wallets for review.
**Acts on:** `human_likelihood`, `trust_tier`, `risk_flags`.

### UC-5 — Verifiable, shareable attestation
**Who:** integrators that must prove a check happened (audit, compliance,
cross-app reuse).
**Need:** a tamper-evident, time-bounded record of the assessment.
**Flow:** store/forward the `proof` object; re-check `expires_at` before
relying on it; re-verify the `signature` (real signing lands in a later
week).
**Acts on:** `proof` (`issued_at`, `expires_at`, `valid_for_hours`,
`signature`).

### UC-6 — Operational use cases (platform)
- **Authentication:** integrators are identified by API key (`X-API-Key`);
  unknown/missing keys are rejected (401).
- **Fair usage:** per-key rate limiting protects the service (429 when
  exceeded) and underpins future metering/billing.
- **Liveness:** `GET /health` for load balancers and uptime checks.

## Non-goals (Week 1 / explicitly out of scope)
- Not identity/KYC: we estimate human-likelihood, not legal identity.
- Not a sanctions/AML oracle (real detectors arrive later).
- Single-chain EVM input only; Solana and other chains are Week 2.
- Week 1 values are deterministic **stubs**; not for production decisions.

## Mapping summary

| Response field | Drives |
| --- | --- |
| `human_likelihood` | Sybil filtering (UC-1), gating (UC-2), governance (UC-4) |
| `trust_tier` | Gating (UC-2), limits (UC-3), vote weight (UC-4) |
| `confidence_score` | Threshold tuning across all use cases |
| `risk_flags` | Exclusion/review triggers (UC-1, UC-3, UC-4) |
| `proof` | Verifiable attestation / reuse (UC-5) |
