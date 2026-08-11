# Deployment runbook (Fly.io)

Production-shaped deployment config for the Trust API. **Not deployed to a paid
host during the internship** — a deliberate cost choice, not a limitation. The
final review runs locally via `docker compose` (see README) and the mock
platform. Everything below is ready for a future operator to run as-is.

## What ships

| Component | Image | Fly shape |
| --- | --- | --- |
| API (`app` process) | `Dockerfile` | HTTP service, port 8000, `/health` check |
| Worker (`worker` process) | `Dockerfile` (same image) | background scoring |
| Dashboard | `Dockerfile.dashboard` | **separate Fly app** (internal only) |
| Postgres | Fly Postgres (managed) | attached |
| Redis | Upstash Redis (Fly add-on) | attached |

The API + worker are one image, two processes (`fly.toml [processes]`). The
Streamlit dashboard is a distinct app because it has its own Dockerfile and
should stay internal (no public route).

## Prerequisites

- A Fly.io account with billing enabled (Postgres/Redis + always-on machines
  are **paid**).
- `flyctl` installed and `fly auth login` done.

## One-time setup

```bash
fly launch --no-deploy --copy-config      # registers the app from fly.toml
fly postgres create --name trust-api-db   # managed Postgres
fly postgres attach trust-api-db          # sets DATABASE_URL secret
fly redis create                          # Upstash Redis -> gives a REDIS_URL
```

## Secrets (never committed)

Set every secret with `fly secrets set` — they are injected as env vars at
runtime and never live in `fly.toml`, the image, or git:

```bash
fly secrets set \
  REDIS_URL="rediss://…"                       # from `fly redis create` \
  API_KEYS="<comma-separated strong keys>" \
  ETHERSCAN_API_KEY="<provider key>" \
  PROOF_SIGNING_KEY="$(python -c 'import base64,os;print(base64.b64encode(os.urandom(32)).decode())')"
# DATABASE_URL is set automatically by `fly postgres attach`.
```

- **`PROOF_SIGNING_KEY`** must be a fixed base64 32-byte seed and kept stable
  across releases, or previously issued proofs stop verifying (the app logs a
  loud warning and mints an ephemeral key if it's unset — never rely on that in
  prod). Generate once, store only in Fly secrets.
- **`API_KEYS`** are the B2B client keys; rotate by editing this secret.
- Dashboard app takes `DASHBOARD_API_KEYS` (or reuses `API_KEYS`).

## Deploy

```bash
fly deploy          # builds Dockerfile, runs `alembic upgrade head`
                    # (release_command) once, then rolls out the new version
fly status          # machines + health
fly logs
```

The release command applies migrations **before** the new version takes traffic,
so a bad migration fails the release without dropping the old version.

## Health checks

- App: `GET /health` → `{"status":"ok"}` (wired in `fly.toml [[http_service.checks]]`,
  15 s interval). Fly won't route to an unhealthy machine.
- Locally the same probe backs the compose `api` healthcheck.
- `GET /metrics` exposes scoring counters (Prometheus text) for scraping.

## Rollback

```bash
fly releases                       # list versions (vN) with status
fly deploy --image <previous-image-ref>   # redeploy a known-good image, OR:
fly releases rollback              # roll back to the previous release
```

Because migrations run in the release command, roll back **code** freely; roll
back **schema** only with a compensating Alembic downgrade
(`alembic downgrade -1`) run as a one-off:

```bash
fly ssh console -C "alembic downgrade -1"   # only if a migration must be undone
```

Prefer forward-fixes over schema rollbacks in production.

## Scaling notes (from docs/performance.md)

- `/verify` is light (100 rps, single-digit-ms p50 cache-warm) — scale
  horizontally with more `app` machines behind the Fly proxy.
- `/verify/batch` is heavy (~5 s per 20-wallet batch under concurrency) and is a
  **background** path. Before high-volume production use, apply the batch
  optimizations in `performance.md` (one transaction per batch, set-based
  feature query, a worker pool). Do not raise the 100-wallet batch cap without
  revisiting the O(N²) graph pass.
