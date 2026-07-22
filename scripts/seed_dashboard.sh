#!/usr/bin/env bash
#
# Manual dashboard seeding for demos — populate the running stack with REAL
# data so the dashboard panels look like production usage.
#
# This is a demo ritual, NOT test data and NOT run automatically (never wired
# into CI, compose, or pytest). Invoke it by hand. It makes real Etherscan
# calls (burns some quota) and only uses real wallets from the committed
# labeled dataset — it never fabricates a score.
#
# Prerequisites (see docs/seed-dashboard.md):
#   1. Stack up:  docker compose up -d
#   2. .env contains a real ETHERSCAN_API_KEY and the demo keys, e.g.:
#        API_KEYS=dev-key,team-alpha-key,team-beta-key,integration-test-key
#        DASHBOARD_API_KEYS=
#        ETHERSCAN_API_KEY=<your key>
#        RATE_LIMIT_PER_MINUTE=25
#      (then re-run `docker compose up -d` so the api picks them up)
#
# Usage:  scripts/seed_dashboard.sh        # run from the repo root
set -euo pipefail

PYTHON="${PYTHON:-.venv/bin/python}"
API_URL="${API_URL:-http://localhost:18000}"
export DATABASE_URL="${DATABASE_URL:-postgresql+psycopg://trust:trust@localhost:55442/trust}"
export REDIS_URL="${REDIS_URL:-redis://redis:6379/0}"
REDIS_URL="${REDIS_URL/redis:6379/localhost:63799}"  # host-port form for host runs
export REDIS_URL

# Load ETHERSCAN_API_KEY (and any keys) from .env for the host-run score job.
set -a; [ -f .env ] && . ./.env; set +a

HEAVY_KEY="${HEAVY_KEY:-team-alpha-key}"
MODERATE_KEY="${MODERATE_KEY:-team-beta-key}"
LIGHT_KEY="${LIGHT_KEY:-integration-test-key}"

if [ -z "${ETHERSCAN_API_KEY:-}" ]; then
  echo "ERROR: ETHERSCAN_API_KEY is not set (needed for real ingestion). See docs/seed-dashboard.md." >&2
  exit 1
fi

# --- 1. Real scoring history from the labeled dataset --------------------
# ~36 wallets spread across projects + both labels. Only real addresses; the
# pipeline skips any wallet whose ingestion fails (never fabricates a score).
BATCH="$(mktemp)"
"$PYTHON" - <<'PY' > "$BATCH"
import json
wallets = json.load(open("data/labeled_wallets.json"))["wallets"]
def take(pred, n):
    return [w["address"] for w in wallets if pred(w)][:n]
picks = (
    take(lambda w: w["label"] == "human", 18)                                  # humans (hop)
    + take(lambda w: w["label"] == "sybil" and w["project"] == "hop", 6)
    + take(lambda w: w["label"] == "sybil" and w["project"] == "safe", 7)
    + take(lambda w: w["label"] == "sybil" and w["project"] == "arbitrum", 5)
)
print("\n".join(picks))
PY
COUNT="$(wc -l < "$BATCH" | tr -d ' ')"
TRAFFIC_WALLET="$(head -1 "$BATCH")"   # already-seeded -> cached, fast for traffic
echo "==> scoring $COUNT real labeled wallets via the pipeline (real ingestion; failures skipped)…"
"$PYTHON" -m trust_api.jobs.score --batch "$BATCH" || true
rm -f "$BATCH"

# --- 2. Realistic multi-key API usage ------------------------------------
# Target an already-seeded wallet so these calls hit cached features (fast, no
# re-ingest); the usage panel counts per-KEY, so the wallet doesn't matter.
call() {
  curl -s -o /dev/null -w "%{http_code} " -X POST "$API_URL/verify" \
    -H "Content-Type: application/json" -H "X-API-Key: $1" \
    -d "{\"wallet\":\"$TRAFFIC_WALLET\",\"chains\":[\"ethereum\"]}"
}
echo; echo "==> heavy user ($HEAVY_KEY): 30 calls (exceeds 25/min -> some 429)…"
for _ in $(seq 1 30); do call "$HEAVY_KEY"; done; echo
echo "==> moderate ($MODERATE_KEY): 10 calls…"; for _ in $(seq 1 10); do call "$MODERATE_KEY"; done; echo
echo "==> light ($LIGHT_KEY): 3 calls…"; for _ in $(seq 1 3); do call "$LIGHT_KEY"; done; echo
echo "==> invalid key: 5 calls (-> 401)…"; for _ in $(seq 1 5); do call "WRONG-KEY"; done; echo
echo "==> malformed wallet: 2 calls (-> 400)…"
# Use the moderate key here: the heavy key is already rate-limited this window,
# which would return 429 before the 400 wallet-format check ever runs.
for _ in 1 2; do
  curl -s -o /dev/null -w "%{http_code} " -X POST "$API_URL/verify" \
    -H "Content-Type: application/json" -H "X-API-Key: $MODERATE_KEY" -d '{"wallet":"0xnothex"}'
done; echo
echo; echo "==> Seeding complete. Open the dashboard (http://localhost:8501) and refresh."
