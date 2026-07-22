# Seeding the dashboard for a demo

A repeatable ritual to fill the internal dashboard with **realistic, real
data** so the panels look like production usage before a live demo.

**This is demo seed data, not test data.** `scripts/seed_dashboard.sh` is run
**by hand** — it is never wired into CI, docker-compose, or pytest. It makes
**real Etherscan calls** (burns some API quota) and uses **only real wallets
from the committed labeled dataset** (`data/labeled_wallets.json`). It never
fabricates a score: any wallet whose ingestion fails is logged and skipped by
the pipeline.

## What it produces

- **Scoring history**: ~36 labeled wallets scored through the real pipeline
  (ingest → features → score → persist), giving a realistic mix of tiers,
  human-likelihood, confidence, and risk flags. Spread: 18 humans (hop) +
  sybils across hop/safe/arbitrum.
- **API usage**: multi-key traffic — a heavy key (~30 calls), moderate (~10),
  light (~3), invalid-key attempts (→ 401), malformed wallets (→ 400), and a
  deliberate rate-limit breach (→ 429) so the Rate-limit-hits counter is
  non-zero.

## Prerequisites

1. **Stack up** (see README): `docker compose up -d`.
2. **`.env`** (gitignored) with a real key and the demo API keys, then
   re-run `docker compose up -d` so the api/dashboard pick them up:

   ```dotenv
   API_KEYS=dev-key,team-alpha-key,team-beta-key,integration-test-key
   DASHBOARD_API_KEYS=
   ETHERSCAN_API_KEY=<your real key>
   RATE_LIMIT_PER_MINUTE=25
   ```

   `RATE_LIMIT_PER_MINUTE=25` lets the heavy key's 30 calls trip the limit so
   the 429 row/counter populate. The script's default key names match the
   `API_KEYS` above; override with `HEAVY_KEY` / `MODERATE_KEY` / `LIGHT_KEY`.
3. A local venv with the package installed (`pip install -e ".[dev]"`) — the
   score step runs on the host as `python -m trust_api.jobs.score`.

## Run it

```bash
# from the repo root
./scripts/seed_dashboard.sh
```

Then open **http://localhost:8501** (login with any `API_KEYS` value, e.g.
`dev-key`) and refresh. Takes ~1 minute (the batch does real ingestion; the
usage traffic targets an already-seeded wallet so it hits cached features and
is fast).

Overridable env: `API_URL` (default `http://localhost:18000`), `DATABASE_URL`
/ `REDIS_URL` (default the compose host ports 55442 / 63799), `PYTHON`
(default `.venv/bin/python`), and the key names above.

## Start clean vs. add more

- **Fresh slate**: `docker compose down -v && docker compose up -d`, then run
  the script. (`-v` wipes the Postgres volume.)
- **Add more traffic**: just run the script again — scoring history upserts
  per `(wallet, scorer_version)` and usage rows accumulate.

## Expected result (rough)

- `trust_score_history`: ~37 distinct wallets.
- Tiers: a spread across bronze / silver / gold (e.g. ~11 / ~17 / ~9).
- Flags: several types present (dormant, bot_burst, low_counterparty_diversity,
  low_activity, sybil_suspected, new_wallet).
- API usage: 3–4 hashed keys with distinct 24h/7d counts, a non-zero
  rate-limit-hits number, and 400/401 rows populated.
- All six panels visually meaningful.

Exact numbers vary with live on-chain data — that's expected; these are real
scores, not fixtures.
