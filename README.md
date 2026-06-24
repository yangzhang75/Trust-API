# Proof-of-Human Trust API

A B2B **Reputation-as-a-Service** API. Given a wallet address, it returns a
human-likelihood assessment, a trust tier, a confidence score, risk flags,
and a time-bounded signed proof.

> ⚠️ **Week 1 (skeleton & contracts).** The `/verify` endpoint runs
> end-to-end but returns **deterministic stub data derived from a hash of
> the wallet** — real blockchain ingestion, scoring/ML, Sybil detection,
> and cryptographic signing are stubbed behind typed interfaces and marked
> with `# TODO(week N)`. See [`docs/architecture.md`](docs/architecture.md)
> and [`docs/engineering-plan.md`](docs/engineering-plan.md).

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

## Project layout

```
src/trust_api/
  main.py            # app factory
  config.py          # pydantic-settings
  api/               # routes.py, deps.py (auth + rate limit)
  schemas/           # verify.py (Pydantic v2 models + enums)
  services/          # ingestion, features, scoring, proof (stubbed)
  db/                # session.py, models.py
  core/              # logging.py
tests/               # health + verify tests
migrations/          # Alembic env + initial migration
docs/                # architecture.md, engineering-plan.md, openapi.json
```

## License

Proprietary — internal internship project.