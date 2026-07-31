# Platform Integration Simulation (Week 10)

A **mock client platform** that consumes the Trust API end-to-end over its
public HTTP interface — the first "eat our own dogfood" test. It is a separate
service (`trust_api/demo/platform/`), talks to the API only via real
`X-API-Key` requests (no internal scoring/proof imports), and keeps its **own**
SQLite metrics store (never the Trust API's Postgres).

> **Headline honesty finding (read this):** on the labeled dataset, the mock
> accepts labeled **sybils at nearly the same rate as humans**. This is not a
> mock bug — it's a real limitation of consuming the API **one wallet at a
> time**. See [Honesty findings](#honesty-findings).

## Architecture

```
labeled wallets ─▶ traffic simulator ─▶ Mock Platform (FastAPI, :8001)
                                          │  POST /mock/login
                                          │  POST /mock/creator/apply
                                          │  POST /mock/filter/batch
                                          │  GET  /mock/stats   ← SQLite
                                          ▼  X-API-Key (HTTP)
                                        Trust API (:8000)
                                          POST /verify, POST /proof/generate
```

## The three scenarios

| Scenario | Endpoint | Trust API calls | Policy |
| --- | --- | --- | --- |
| **A — Social login** | `POST /mock/login {wallet}` | `/verify` | reject `sybil_suspected`; accept silver+; accept-but-flag bronze → `{accepted, tier, reason}` |
| **B — Creator verification** | `POST /mock/creator/apply {wallet}` | `/verify` (+ `/proof/generate` on pass) | gold only; issue a proof on approval → `{approved, tier, reason, proof?}` |
| **C — Bot filtering** | `POST /mock/filter/batch {wallets:[…]}` | `/verify` per wallet | remove `sybil_suspected` or `low` human-likelihood; keep the rest → `{kept:[…], removed:[…]}` |

Error handling reflects a real client: a Trust API `400` (invalid wallet) is a
normal rejection; other upstream failures (auth/rate-limit/outage) surface as a
`502` on the single-wallet endpoints, while the **batch** endpoint isolates
per-wallet failures (one bad/rate-limited wallet is marked `removed`, it does
not fail the whole batch).

## How to run

The mock runs alongside the Trust API via compose (host port `18001` locally):

```bash
docker compose up -d                     # brings up api, worker, dashboard, mock
curl -s localhost:18001/mock/health      # {"status":"ok","trust_api_url":"http://api:8000"}
```

Then pump traffic and read the stats:

```bash
# 24 labeled wallets (12 human / 12 sybil) through all three scenarios
MOCK_URL=http://localhost:18001 SIM_WALLETS=24 \
  .venv/bin/python -m trust_api.demo.platform.simulate

curl -s localhost:18001/mock/stats | python3 -m json.tool
```

> **Rate limit:** the simulator makes ~72 `/verify` calls in a burst on one key.
> The default `RATE_LIMIT_PER_MINUTE` will 429 most of them. Raise it for the
> run: `RATE_LIMIT_PER_MINUTE=5000 docker compose up -d api`. (This is itself a
> DX finding — see below.)

## Interpreting `/mock/stats`

Per scenario: `total`, `accepted`, `rejected`, `acceptance_rate`,
`avg_latency_ms` (wall-time of the Trust API call(s) for that decision), and
`tiers` / `reasons` breakdowns. For scenario C, `accepted` = kept.

## Real numbers from an actual run

24 wallets (12 labeled human / 12 labeled sybil), live Trust API, scorer
`0.4.0-graph`:

| Scenario | total | accepted | acceptance rate | avg latency | tiers |
| --- | --- | --- | --- | --- | --- |
| login | 24 | 23 | **95.8%** | 296.1 ms | silver 15 / gold 7 / bronze 2 |
| creator | 24 | 7 | **29.2%** | 5.5 ms | silver 15 / gold 7 / bronze 2 |
| filter | 24 | 22 (kept) | **91.7%** | 3.0 ms | silver 15 / gold 7 / bronze 2 |

- **Login** rejected exactly 1 wallet (the only `sybil_suspected`); accepted 22
  as `tier_ok` and flagged 1 bronze.
- **Creator** approved the 7 gold wallets (and issued 7 real proofs); rejected
  the 17 below gold.
- **Filter** removed 2 (1 `sybil_suspected`, 1 `low_human_likelihood`).
- **Latency:** login shows ~296 ms because it ran first and triggered on-demand
  ingestion (real Etherscan round-trips) on cache misses; creator/filter then
  hit cached features (~3–5 ms). So the number is dominated by first-touch
  ingestion, not scoring.

## Honesty findings

### 1. Acceptance rates do NOT reflect the human/sybil labels

Half the input is labeled **sybil**, yet login accepted 23/24 and filter kept
22/24. Scored one wallet at a time, humans and sybils are nearly
indistinguishable:

| label | silver | gold | bronze | `sybil_suspected` |
| --- | --- | --- | --- | --- |
| human (12) | 7 | 4 | 1 | 0 |
| sybil (12) | 8 | 3 | 1 | **1** |

Only **1 of 12** labeled sybils carried `sybil_suspected`; the rest scored
silver/gold and sailed through. This does **not** match the scoring engine's
headline accuracy — and here's why.

### 2. Root cause: single-wallet `/verify` never populates the graph features

The scorer is `0.4.0-graph`: its sybil signal comes from **cluster** features —
`shared_funder_score`, `counterparty_overlap_score`, `cluster_size_estimate`,
`funding_chain_depth`. Inspecting the sampled sybils in the DB, **every one of
those columns is `NULL`**:

```
addr…                                       shared_funder cp_overlap cluster_size fund_depth
0x14f319…819656                             None          None       None         None
0x2542138c…919449                           None          None       None         None
…  (all 12 sampled sybils identical)
```

On-demand `/verify` ingests **only the queried wallet**, not its cluster/
siblings, so the graph features that detect farming clusters are never computed.
The wallet is then scored on its solo activity — which for an active farming
wallet looks like a normal silver/gold user. **A client calling `/verify` per
wallet gets materially weaker sybil detection than the engine's cluster-complete
evaluation.** This is a genuine architectural finding, not smoothing: the mock
faithfully reports what the API returns.

Mitigation (out of scope for the mock): the sybil signal needs a cluster-aware
path — batch-ingest a wallet's counterparties before scoring, or a dedicated
bulk endpoint that ingests + scores a cohort together.

### 3. Developer-experience (DX) friction — first dogfood pass

- **No bulk endpoint.** Scenario C must fan out N sequential `/verify` calls
  (N HTTP round-trips + N on-demand ingests). A real bulk consumer wants one
  request — and, per finding #2, a bulk path is also what sybil detection needs.
- **Rate limit bites bursts.** ~72 `/verify` calls trip the default limit
  immediately; we had to raise `RATE_LIMIT_PER_MINUTE`. Any batch consumer will
  hit this on day one.
- **`/proof/generate` re-scores.** Scenario B calls `/verify` then
  `/proof/generate`, which ingests + scores the wallet **again** — there's no
  way to mint a proof for an assessment you already hold. Wasteful for a client
  that just verified.
- **Field names are implicit.** A client must know `trust_tier`,
  `human_likelihood`, `risk_flags`; `400` (invalid wallet) must be special-cased
  vs. other errors. Minor, but undocumented for external consumers.

### 4. Scope honesty

The scenarios are intentionally shallow (breadth over depth, per the brief):
policies are a handful of tier/flag rules, "sessions"/"creators" aren't
modeled, and the metrics store is a single SQLite table. They are functional and
end-to-end, but they are mocks — the value here is the integration proof and the
findings above, not the platform logic.
