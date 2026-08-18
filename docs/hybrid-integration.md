# Hybrid integration: `/verify` + `/verify/batch` (Week 11)

Two endpoints implement the "Twitter model" of moderation — an **instant**
decision at signup, then a **background batch re-score** with fuller context.

| | `POST /verify` | `POST /verify/batch` |
| --- | --- | --- |
| When | real-time, one wallet | background, many wallets together |
| Graph (cluster) features | **not computed** (a single wallet has no neighbors) | **computed across the batch** — the batch is the graph context |
| Latency | one ingest + score | N ingests + one graph pass + N scores |
| Rate limit | 1 request | **1 request** (not N) — batch to save budget |
| Response | assessment + proof | array (input order) of assessment + proof + `graph_context_size` |
| Batch size | — | ≤ 100 wallets (else `400`, split the call) |

## The pattern: register instantly, re-score in batch

```
signup ──▶ POST /verify (instant: accept silver+, reject sybil) ──▶ let the user in
                                                                        │
        every ~15 min ─▶ POST /verify/batch(recent signups) ─▶ graph features populated
                                                                        │
                              flips to sybil/bronze? ──▶ retroactively suspend
```

The Week-10 mock implements exactly this (`trust_api/demo/platform/`):

```python
# instant, at signup
resp = client.verify(wallet)          # POST /verify — no graph context
if decide_login(resp).accepted:
    store.upsert_account(wallet, resp["trust_tier"])

# background job, scheduled every ~15 min (cron / APScheduler)
def rescore_recent(store, client):
    wallets = store.recent_active_accounts(since_minutes=15)
    for r in client.verify_batch(wallets):        # POST /verify/batch — graph context
        if "sybil_suspected" in r["risk_flags"] or r["trust_tier"] == "bronze":
            store.suspend_account(r["wallet"], reason=...)   # retroactive
```

`POST /mock/rescore` forces the job immediately for demos.

## Reading `graph_context_size`

Each batch result carries `graph_context_size` — the wallet's connected-component
size within the batch. **Larger = more graph evidence.** `graph_context_size == 1`
means the wallet was isolated (no shared funders/counterparties with the others),
and a `graph_context_note` says so: it was effectively scored like a single
`/verify`. Use it to decide how much to trust the graph-derived part of a score.

## Measured validation (Week 12): the two modes really are complementary

Measured on the 246-wallet expanded pool (unchanged `v0.5.0` scorer,
`human_likelihood` rule, 2026-08-17; full tables in
[`final-presentation.md`](final-presentation.md) and
[`accuracy-gap.md`](accuracy-gap.md)):

| | Single `/verify` (graph NULL) | `/verify/batch` (graph) |
| --- | --- | --- |
| Human false-positive rate | **~1%** (0.8% balanced) | **~42%** (42.5% balanced) |
| Sybil recall (balanced) | 39.2% | **79.2%** |
| Social 95/5 accuracy | **96.9%** | 58.6% |
| Airdrop 30/70 accuracy | 57.1% | **72.9%** |

This is the empirical case for the hybrid pattern: **single is human-friendly but
sybil-permissive; batch is sybil-hunting but human-costly.** Use single for the
instant, human-facing decision (so real users aren't rejected — ~1% FP) and batch
for the background sybil sweep (where ~79% recall is worth the FP cost, mitigated
by the appeal/grace path below). Caveat: single's 96.9% on social is partly
*conservative scoring* on a human-heavy mix (it flags almost no one), not superior
discrimination — on a sybil-heavy population single drops to 57.1%. Neither mode is
universally "better"; they fail in opposite directions, which is why you run both.

## ⚠️ Tradeoffs (do not pretend these away)

- **Retroactive suspension is a real UX cost.** A user can sign up, be active,
  and then be suspended minutes later when the batch sees their cluster. This is
  inherent to the hybrid model — Twitter has the exact same "you were fine,
  now you're limited" problem. Surface it to users (appeal path, grace period);
  don't hide it.
- **Graph context only helps when the batch is a real neighborhood.** Batching
  an *arbitrary* set of wallets over-connects them (they share mainstream
  counterparties like popular DEXs/stablecoins), collapsing everyone into one
  giant component and dropping *legitimate* users to bronze too. On our balanced
  test set this did **not** improve accuracy — see
  [`accuracy-gap.md`](accuracy-gap.md). Batch wallets that plausibly belong to
  the same neighborhood (same campaign, same time window, same referrer), not a
  random mix.
- **Performance.** The graph pass is **O(N²)** in batch size (pairwise
  counterparty-overlap + adjacency), which is fine at the 100-wallet cap but not
  beyond — do not raise the cap without changing the algorithm. The dominant
  real cost is ingestion: a cold batch makes up to N sequential provider
  (Etherscan) calls. Warm caches make re-scores cheap; cold batches are slow and
  burn provider quota.

## Errors

`/verify/batch` returns `400` for > 100 wallets or any invalid address (with the
offending ones named). A malformed body is `422`. Auth is the same API key as
`/verify`; the whole batch counts as **one** rate-limited request.
