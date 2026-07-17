# Internal monitoring dashboard (Week 8)

An **internal** operations dashboard for answering two questions quickly:
*"what is the system doing right now?"* and *"why did this wallet get this
score?"*. It favors information density and lookup speed over visual polish.

It is a **separate Streamlit process** that reads the same Postgres + Redis as
the API; it is not coupled into the FastAPI app.

## Why Streamlit (not React)

For an internal monitoring tool, React is overkill: it would mean a build
toolchain, a separate API surface, and hand-written data-fetching for what is
essentially "run a query, show a table/chart." Streamlit renders dense tables
and charts directly from Python with almost no UI code, so effort goes into
the (tested) data layer instead of a frontend. The trade-off — Streamlit's
auth and multi-user story are weak — is acceptable for an internal tool and is
handled explicitly below.

## Architecture

```
dashboard/streamlit_app.py   UI only (renders; not unit-tested)
        │  calls
        ▼
trust_api/dashboard/data.py  tested query/aggregation layer (100% covered)
trust_api/dashboard/auth.py  API-key gate (tested)
        │  reads
        ▼
Postgres (existing tables)  +  Redis (H1 shared metrics)
```

The split is deliberate: **all data access lives in `trust_api.dashboard`**
(no streamlit import, fully unit-tested); the Streamlit file only arranges
widgets. This is also why the Streamlit deps (`streamlit`, `pandas`) live in
an optional `dashboard` extra and a separate `Dockerfile.dashboard` — the API
image, the worker image, and the CI test env stay lean.

## Running it

### docker-compose (alongside the API)

```bash
# from repo root
DASHBOARD_API_KEYS=some-admin-key docker compose up dashboard
# open http://localhost:8501  and enter the key
```

`docker compose up` brings up postgres, redis, api, worker, and dashboard
together. The dashboard waits for postgres/redis to be healthy.

### Locally (without Docker)

```bash
pip install -e ".[dashboard]"
export DATABASE_URL=postgresql+psycopg://trust:trust@localhost:5432/trust
export REDIS_URL=redis://localhost:6379/0
export DASHBOARD_API_KEYS=some-admin-key         # or rely on API_KEYS
streamlit run dashboard/streamlit_app.py --server.port 8501
```

## Auth (and its limits — read this)

Access is gated by the **same key mechanism as the rest of the service**
(`trust_api.dashboard.auth.verify_dashboard_key`, constant-time compare):

- A key in `DASHBOARD_API_KEYS` (the admin tier) **or** any key in `API_KEYS`
  grants access.
- With **no** keys configured the dashboard is **closed** (rejects everything)
  — it is never publicly accessible by default.

**Known limits (not hidden):** Streamlit has no built-in authentication, so
this is an **app-level gate**, not a network-level one:

- The gate runs *inside* the app. Anyone who can reach port 8501 can load the
  login page; they just can't see panels without a valid key.
- The key is entered in a form and held in Streamlit `session_state` for the
  browser session. It is not a signed session token.
- There is no per-user identity, audit log, or role separation beyond
  "admin key vs regular key."

For anything beyond internal/trusted-network use, put the dashboard behind a
real auth proxy (e.g. an SSO/oauth2 sidecar) or restrict port 8501 to a VPN.

## Panels and their data sources

| Panel | Shows | Reads from |
| --- | --- | --- |
| **Overview** | wallets scored (all-time / 24h), /verify calls, 24h success ratio, avg scoring time, last-scoring timestamp ("is it alive?"), scorer_version | `trust_score_history`, `usage_events`†, Redis metrics (H1) |
| **Score distribution** | tier / human-likelihood / confidence-bucket distributions over the latest score per wallet, time-filterable (24h/7d/30d/all) | `trust_score_history` |
| **Risk flags** | most-frequent flags; recent flagged wallets (expandable to features + history + proofs) | `trust_score_history`, `wallet_features`, `proofs` |
| **Wallet inspector** | paste an address → features, all historical scores (versions + timestamps), proof metadata | `wallets`, `wallet_features`, `wallet_transactions`, `trust_score_history`, `proofs` |
| **API usage** | per-key call counts (24h/7d), 429 hits, failed requests by status | `usage_events`†, `api_keys`† |
| **System health** | Postgres/Redis up-down, shared scoring metrics snapshot | Redis metrics (H1), live DB/Redis probes |

† **Known data-source limit (surfaced, not faked):** the API currently
authenticates against the configured key list and does **not** write
`usage_events` or `api_keys` rows. So the **API usage** panel and the
Overview's `/verify` counts / success ratio are **empty today** — the panels
render with an explicit "empty by design, not an outage" caveat rather than
showing fabricated numbers. When request-logging is added (writing a
`usage_events` row per request), these panels light up with no dashboard
change.

**Deferred:** recent structured error logs are not surfaced. Logs stream to
each container's stdout/stderr and there is no log store to query; the health
panel says so rather than pretending. Adding this would mean shipping logs to
a store (Loki/ELK/a table) first.

## The "why did this wallet get this score?" flow

Use the **Wallet inspector**: paste the address. You get the wallet's computed
features (the exact inputs to the rule engine), every historical score with
its `scorer_version` and timestamp (so you can see score changes across scorer
versions), and any issued/revoked proofs. Cross-reference the features against
the thresholds in `scoring/config.py` to see which rules fired.

## Adding a new panel

1. Add a query/aggregation function to `trust_api/dashboard/data.py` that
   returns **plain Python** (dicts/lists) — no streamlit. Accept
   `since: datetime | None` if it should be time-filterable, and an optional
   `now` for deterministic tests.
2. Add tests to `tests/test_dashboard_data.py` that seed a known DB state and
   assert the returned counts/shape. Keep coverage at 100%.
3. Add a `def my_panel(session, ...)` to `dashboard/streamlit_app.py` that
   calls your data function and renders it, and wire it into `main()`.
4. If a data source has limits (empty table, sampling), show a caveat in the
   panel — do not imply zero/complete data.
