# Proof-of-Human Trust API

A B2B **Reputation-as-a-Service** API. Given a wallet address, it returns a
human-likelihood assessment, a trust tier, a confidence score, risk flags,
and a time-bounded signed proof.

> ⚠️ **Week 1 (skeleton & contracts).** The `/verify` endpoint runs
> end-to-end but returns **deterministic stub data derived from a hash of
> the wallet** — real blockchain ingestion, scoring/ML, Sybil detection,
> and cryptographic signing are stubbed behind typed interfaces and marked
> with `# TODO(week N)`. See [`docs/api-use-cases.md`](docs/api-use-cases.md),
> [`docs/architecture.md`](docs/architecture.md), and
> [`docs/engineering-plan.md`](docs/engineering-plan.md).

## Tech stack

Python 3.11+ · FastAPI + Uvicorn · Pydantic v2 · SQLAlchemy 2.0 + Alembic ·
PostgreSQL 16 · Redis 7 · pytest · ruff + black · Docker + docker compose ·
GitHub Actions.

## Quick start (Docker)

```bash
docker compose up --build
```

This starts **api + postgres + redis**, applies migrations, and serves the
API on `http://localhost:8000`. The default dev API key is `dev-key`
(override via the `API_KEYS` env var — never use the default outside local
dev).

Verify it's up:

```bash
# Health
curl localhost:8000/health
# -> {"status":"ok"}

# Verify a wallet (valid EVM address + API key)
curl -s -X POST localhost:8000/verify \
  -H "Content-Type: application/json" \
  -H "X-API-Key: dev-key" \
  -d '{"wallet":"0x52908400098527886E0F7030069857D2E4169EE7","chains":["ethereum"]}'
```

Example `200` response:

```json
{
  "wallet": "0x52908400098527886E0F7030069857D2E4169EE7",
  "human_likelihood": "medium",
  "trust_tier": "silver",
  "confidence_score": 0.6703,
  "risk_flags": ["low_activity"],
  "chains": ["ethereum"],
  "proof": {
    "issued_at": "2026-06-24T18:00:00+00:00",
    "expires_at": "2026-06-25T18:00:00+00:00",
    "valid_for_hours": 24,
    "signature": "stub-…"
  }
}
```

Error behavior: invalid wallet → `400`, missing/invalid API key → `401`,
malformed body → `422`, rate limit exceeded → `429`.

Interactive API docs (Swagger UI) render at
[`http://localhost:8000/docs`](http://localhost:8000/docs).

## Local development (without Docker)

Requires a local Postgres and Redis (or point the env vars at the compose
services). Then:

```bash
python -m venv .venv && source .venv/bin/activate
make install                 # pip install -e ".[dev]"
cp .env.example .env         # adjust as needed
make migrate                 # alembic upgrade head
make run                     # uvicorn with autoreload on :8000
```

## Common tasks (Makefile)

```bash
make install   # install package + dev deps
make run       # run the API locally (autoreload)
make up        # docker compose up --build (api + postgres + redis)
make down      # stop services and remove volumes
make test      # pytest with coverage
make lint      # ruff check + black --check
make fmt       # ruff --fix + black
make migrate   # alembic upgrade head
make openapi   # export docs/openapi.json
```

## Tests

```bash
make test
```

Covers `/health`, the `/verify` stub `200`, determinism, invalid wallet
`400`, missing/invalid API key `401`, and malformed body `422`. Target
coverage ≥80%.

## Configuration

All settings are read from the environment (see [`.env.example`](.env.example)):

| Variable | Default | Purpose |
| --- | --- | --- |
| `API_KEYS` | _(empty)_ | Comma-separated allowlist of accepted API keys |
| `RATE_LIMIT_PER_MINUTE` | `60` | Per-key fixed-window rate limit (Redis) |
| `DATABASE_URL` | `postgresql+psycopg://trust:trust@localhost:5432/trust` | Postgres DSN |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis URL |
| `PROOF_VALID_FOR_HOURS` | `24` | Proof validity window |
| `ENVIRONMENT` / `LOG_LEVEL` | `development` / `INFO` | App metadata / logging |
| `ETHERSCAN_API_KEY` | _(empty)_ | Web3 provider key; blank disables live ingestion |
| `INGESTION_CACHE_TTL_SECONDS` | `21600` | Redis TTL for cached wallet history (0 = off) |
| `WORKER_INTERVAL_SECONDS` | `3600` | Background worker refresh interval |

## Blockchain data ingestion (Week 2)

A real ingestion service fetches a wallet's transaction history across
**Ethereum and Arbitrum** from **Etherscan (V2 unified API)** and stores it in Postgres via an
idempotent ETL pipeline, driven by a background worker. See
[`docs/ingestion.md`](docs/ingestion.md) for the provider rationale, ETL
flow, and data model.

```bash
make migrate                 # apply migrations (adds wallet_transactions)
export ETHERSCAN_API_KEY=... # optional; never commit. Blank = register-only
make seed                    # seed data/labeled_wallets.json
make worker                  # one ingestion pass (or `python -m trust_api.worker`)
make features                # compute behavioral features (docs/features.md)
```

The provider key is read from the environment only and must never be
committed (`.env.example` ships it blank). Without a key the API and worker
still run — wallets are registered without transaction history. The
`/verify` contract is unchanged; ingested data feeds later weeks, never the
public API (raw transactions are internal-only).

## Project layout

```
src/trust_api/
  main.py            # app factory
  config.py          # pydantic-settings
  worker.py          # background ingestion worker (APScheduler)
  api/               # routes.py, deps.py (auth + rate limit)
  schemas/           # verify.py (Pydantic v2 models + enums)
  jobs/              # compute_features, evaluate_scoring (CLIs)
  services/
    ingestion/       # provider + transform + load (real, Week 2)
    features/        # SQL-aggregated behavioral features (real, Week 3)
    scoring/         # transparent rule engine + config (real, Week 4)
    proof.py         # still stubbed (Week 6)
  db/                # session.py, models.py
  core/              # logging.py
data/                # labeled_wallets.json (verified labeled dataset)
scripts/             # seed_wallets.py, export_openapi.py
tests/               # health, verify, ingestion, ETL, features, scoring, eval
migrations/          # Alembic (0001 schema, 0002 txs, 0003 feature cols)
docs/                # architecture, ingestion, features, scoring, scoring-eval, ...
```

## Trust scoring (Week 4)

`/verify` returns real scores from a transparent, deterministic rule
engine (no ML) — see [`docs/scoring.md`](docs/scoring.md) for every rule,
weight, and threshold. Accuracy is evaluated on a **held-out test split** of a verified labeled
dataset ([`docs/dataset.md`](docs/dataset.md)) and reported honestly in
[`docs/scoring-eval.md`](docs/scoring-eval.md) — currently **54.55%
test-split** (down from a Week-4 83.33% that turned out to be a "thin
mainnet" artifact once L2 data was added; see the report):

```bash
python -m trust_api.jobs.split              # (re)build the committed train/test split
python -m trust_api.jobs.evaluate_scoring   # regenerate the eval report
```

## Scoring pipeline (Week 5)

The scoring path is an operable, scheduled pipeline (ingest → features →
score → persist) with per-wallet failure isolation, append-only score
history, structured JSON logs, and counters at `GET /metrics`. See
[`docs/pipeline.md`](docs/pipeline.md).

```bash
python -m trust_api.jobs.score --wallet 0x...          # one wallet
python -m trust_api.jobs.score --refresh-stale --hours 24
python -m trust_api.jobs.score --refresh-all           # or `make score`
```

## License

Proprietary — internal internship project.