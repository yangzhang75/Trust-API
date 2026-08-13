# Scoring v2 — experiment log

Full record of each scoring-v2 experiment: what was tried, before/after on both
test sets, ablation, pre-set red lines, and the ship/revert decision. Every
number here is reproducible on the current data snapshot with the stated flags;
where a reported number could **not** be reproduced, that is stated explicitly.

Conventions: **balanced** = 24 wallets (12 human / 12 sybil) scored as one
`/verify/batch`; **holdout TEST** = the sybil-heavy Week-4 held-out split (28
wallets); recall is likelihood-based (`human_likelihood == low → sybil`) unless
noted. Production baseline entering v2: **`0.5.0-threshold-v2`** — balanced
62.5%, holdout TEST 82.14%, sybil recall 67%.

---

## Experiment 1 — Rare-counterparty filter → **REVERTED (negative result)**

**Hypothesis.** Graph over-connection is driven by shared mainstream
infrastructure (DEXs, stablecoins, WETH, bridges). Excluding counterparties that
touch >20% of all dataset wallets from graph edges should reduce spurious
human–human overlap and improve the balanced set.

**Pre-check (gate).** Top-20 highest-degree counterparties were confirmed to be
shared infrastructure — USDC/USDT/WETH/native-USDC (Arbitrum + mainnet), ARB,
Uniswap V2/V3/Universal, SushiSwap, Balancer Vault, Arbitrum bridges — and all
had **0% inbound** (none are funders). Gate passed; proceeded.

**Change.** `graph.py` skips high-degree counterparties (ratio 0.20, a-priori,
not tuned) when building funder/counterparty edges. Behind
`RARE_COUNTERPARTY_FILTER_ENABLED`, default **off**.

**Pre-set red lines.** Balanced improves ≥5 pts (≥67.5%) **OR** holdout TEST
stays ≥79%; revert only if neither holds.

**Measured (this harness, reproducible):**

| config | balanced acc | balanced recall | holdout TEST |
| --- | --- | --- | --- |
| filter off (baseline) | 62.5% | 67% (8/12) | 82.14% |
| filter **on** | **62.5%** (no change) | **67%** (no change) | **85.71%** (+3.6 pts) |
| ablation (off) | 62.5% | 67% | 82.14% |

Ablation confirms the holdout change is attributable to the filter.
Investigation: the filter *is* active (17/24 balanced overlaps dropped) but the
24-wallet batch stays one component (`cluster_size` 23) via **non-infra** shared
counterparties, so no balanced tier flipped.

**Reported but NOT reproduced.** The reviewer observed, in a separate run, a
sybil-recall collapse **67% → 17%** (and balanced 62.5% → 58.3%, holdout
unchanged). None of these reproduced in this offline harness (recall stayed 67%,
holdout *improved*). The discrepancy is unresolved — likely a different cohort or
metric — and is itself a reason for caution.

**Decision: REVERT.** Even though the pre-set red line's holdout arm technically
held, the change (a) did **not** achieve its purpose — the balanced set was
unchanged — and (b) carries a real, severe downside: a blanket high-degree
filter can strip a *farming funder* that happens to exceed the 20% degree
threshold, collapsing sybil recall. Missing sybils in production is far worse
than a holdout-only gain. Reverted to `0.5.0-threshold-v2`.

**Revert state.** `RARE_COUNTERPARTY_FILTER_ENABLED` default **false**;
`SCORER_VERSION` stays `0.5.0-threshold-v2` (no new version). The implementation
is **kept behind the flag** — a *partial or weighted* filter (e.g. exclude only
0-inbound infra, or down-weight rather than drop) is a plausible future
experiment with a different design.

**Interpretation.** Filtering out *all* high-degree counterparties is too
aggressive: it removes noise (infra) but also risks removing signal (shared
farming funders). The next attempt would need to distinguish infra (0% inbound,
contract) from funders (inbound EOA) rather than filtering purely on degree.
