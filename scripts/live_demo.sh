#!/usr/bin/env bash
#
# Live demo of the Trust API against the LOCAL docker-compose stack (no remote
# host — deployment to a paid host is skipped for the internship review; see
# docs/deployment.md). Walks the full journey with visible output:
#   /verify (+ cache) -> /verify/batch (graph) -> proof generate/verify ->
#   mock platform scenarios -> hybrid re-score.
#
# Usage:  scripts/live_demo.sh        # from the repo root
#
# Ports default to the compose defaults (api 8000, mock 8001). On a machine that
# remaps host ports (docker-compose.override.yml), pass them explicitly, e.g.:
#   API_URL=http://localhost:18000 MOCK_URL=http://localhost:18001 scripts/live_demo.sh
set -euo pipefail

API_URL="${API_URL:-http://localhost:8000}"
MOCK_URL="${MOCK_URL:-http://localhost:8001}"
DASHBOARD_URL="${DASHBOARD_URL:-http://localhost:8501}"
API_KEY="${API_KEY:-dev-key}"
PY="${PYTHON:-python3}"

pp() { "$PY" -m json.tool; }
hdr() { echo; echo "======================================================================"; echo "  $1"; echo "======================================================================"; }

# Two real labeled wallets for the demo.
read -r W1 W2 <<EOF
$("$PY" - <<'PYEOF'
import json
w = json.load(open("data/labeled_wallets.json"))["wallets"]
print(w[0]["address"], w[1]["address"])
PYEOF
)
EOF

hdr "0. Bring up the local stack (docker compose)"
docker compose up -d
echo "waiting for api + mock health…"
for _ in $(seq 1 40); do curl -sf "$API_URL/health" >/dev/null 2>&1 && break; sleep 2; done
for _ in $(seq 1 40); do curl -sf "$MOCK_URL/mock/health" >/dev/null 2>&1 && break; sleep 2; done
curl -s "$API_URL/health"; echo

hdr "1. /verify — single wallet (note the X-Cache header: MISS then HIT)"
curl -s -D - -o /dev/null -X POST "$API_URL/verify" -H "Content-Type: application/json" \
  -H "X-API-Key: $API_KEY" -d "{\"wallet\":\"$W1\"}" | grep -i "^x-cache" || true
curl -s -D - -o /dev/null -X POST "$API_URL/verify" -H "Content-Type: application/json" \
  -H "X-API-Key: $API_KEY" -d "{\"wallet\":\"$W1\"}" | grep -i "^x-cache" || true

hdr "2. /verify/batch — wallets scored together (graph_context_size populated)"
curl -s -X POST "$API_URL/verify/batch" -H "Content-Type: application/json" \
  -H "X-API-Key: $API_KEY" -d "{\"wallets\":[\"$W1\",\"$W2\"]}" | pp

hdr "3. Proof: generate a shareable proof, then verify it"
ENC=$(curl -s -X POST "$API_URL/proof/generate" -H "Content-Type: application/json" \
  -H "X-API-Key: $API_KEY" -d "{\"wallet\":\"$W1\"}" | "$PY" -c "import sys,json;print(json.load(sys.stdin)['encoded'])")
curl -s -X POST "$API_URL/proof/verify" -H "Content-Type: application/json" \
  -H "X-API-Key: $API_KEY" -d "{\"encoded\":\"$ENC\"}" | pp

hdr "4. Mock platform — three integration scenarios"
echo "-- social login:"; curl -s -X POST "$MOCK_URL/mock/login" \
  -H "Content-Type: application/json" -d "{\"wallet\":\"$W1\"}" | pp
echo "-- creator apply:"; curl -s -X POST "$MOCK_URL/mock/creator/apply" \
  -H "Content-Type: application/json" -d "{\"wallet\":\"$W1\"}" | pp
echo "-- bot filter batch:"; curl -s -X POST "$MOCK_URL/mock/filter/batch" \
  -H "Content-Type: application/json" -d "{\"wallets\":[\"$W1\",\"$W2\"]}" | pp

hdr "5. Hybrid re-score (force the background batch job now)"
curl -s -X POST "$MOCK_URL/mock/rescore" | pp
echo "-- usage stats:"; curl -s "$MOCK_URL/mock/stats" | pp

hdr "Done — full journey demonstrated locally. Dashboard: $DASHBOARD_URL (login: $API_KEY)."
