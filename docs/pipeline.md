# Scoring Pipeline (Week 5)

Turns the per-request scoring into an operable, scheduled pipeline:
**ingest → features → score → persist**, for one wallet or a batch, with
per-wallet failure isolation, append-only history, structured logs, and
metrics. Scoring logic and the `/verify` contract are unchanged.

## End-to-end flow

```
 addresses ─▶ for each wallet (isolated):
                ingest (ETH + Arbitrum)
                  └▶ features (SQL aggregation)
                       └▶ score (rule engine + graph features)
                            └▶ persist -> trust_score_history
              └▶ batch summary
```

Code: `src/trust_api/pipeline.py` — `score_wallet(session, address, settings)`
and `score_wallets(session, addresses, settings)`.

- **Per-wallet isolation:** each stage is wrapped; a failure rolls back the
  session and returns an error `WalletOutcome` tagged with the failed stage
  — it never raises, so one bad wallet can't break the batch (same
  discipline as the Week 2 worker).
- **Idempotent:** persistence upserts on `(wallet_id, scorer_version)`.

## History table — `trust_score_history`

Append-only across scorer versions; one row per `(wallet_id,
scorer_version)`.

| column | notes |
| --- | --- |
| `wallet_id` | FK → wallets |
| `human_likelihood` / `trust_tier` | the assessment |
| `confidence_score` | numeric(5,4) |
| `risk_flags` | jsonb |
| `scorer_version` | e.g. `0.4.0-graph` — bump on any scoring change |
| `scored_at` | timestamptz |

Re-running the **same** `scorer_version` updates that row in place (no
duplicate history); a **version bump** appends a new row, so scores from
different scorer versions stay distinguishable. Migration:
`0005_trust_score_history`.

## Job runner — `python -m trust_api.jobs.score`

| mode | what it does |
| --- | --- |
| `--wallet 0x...` | score one wallet |
| `--batch file.txt` | score every address in the file (one per line) |
| `--refresh-stale --hours N` | score wallets whose latest score is older than N hours |
| `--refresh-all` | score every known wallet |

The background **worker** runs the pipeline on a schedule: `scheduled_score()`
re-scores wallets staler than `WORKER_STALE_HOURS` every
`WORKER_INTERVAL_SECONDS`.

## Structured logs

One JSON line per stage per wallet, plus one `batch_summary` line per batch.
No raw transaction content is ever logged (privacy).

```json
{"ts": "2026-07-12T...", "stage": "ingest", "status": "ok", "duration_ms": 812.4, "wallet": "0x…", "scorer_version": "0.4.0-graph"}
{"ts": "2026-07-12T...", "stage": "score", "status": "error", "error_type": "ValueError", "duration_ms": 1.2, "wallet": "0x…", "scorer_version": "0.4.0-graph"}
{"ts": "2026-07-12T...", "event": "batch_summary", "total": 50, "ok": 48, "failed": 2, "duration_ms": 41230.0, "scorer_version": "0.4.0-graph"}
```

## Metrics — `GET /metrics`

Prometheus text format:

```
wallets_scored_total 48
wallets_failed_total 2
scoring_duration_seconds_count 50
scoring_duration_seconds_avg 0.82
scoring_duration_seconds_min 0.31
scoring_duration_seconds_max 2.10
```

**Caveat:** counters are in-process. The API process only reflects scoring
done in-process; a separate worker process has its own counters. A shared
metrics backend is out of scope this week.
