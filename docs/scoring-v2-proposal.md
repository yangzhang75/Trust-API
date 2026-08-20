# Scoring v2 proposal — closing the balanced-accuracy gap

**Status:** proposal. Motivated by [`accuracy-gap.md`](accuracy-gap.md) and the
validated experiment in [`threshold-experiment.md`](threshold-experiment.md).
All items are scoring-logic changes (thresholds/rules), deliberately kept out of
Weeks 11–12 and gathered here for a dedicated scoring pass.

## Problem (recap)

On a **balanced** 12-human/12-sybil set, both single `/verify` and
`/verify/batch` score ~54% — far below the 78.6% cluster-aware headline. Precise
cause: the graph `sybil_cluster` flag fires on **everyone** (humans 12/12)
because the `cluster_size` signal is corrupted by over-connection (arbitrary
cohorts share mainstream counterparties → one giant component), and
`CLUSTER_MIN_SIGNALS = 1` lets that single always-true signal trip the flag. The
one genuinely discriminating feature, `counterparty_overlap` (0.47 sybil vs 0.10
human), is drowned out.

**Update (Week 12) — this is a *batch-mode* problem, not the whole story.** The
expanded 246-wallet evaluation (Fix 4 below) measured both production paths under
realistic class ratios. The ~54%/over-connection failure is specific to **batch**
(graph) mode; **single `/verify`** (graph NULL) is actually **strong on
production-realistic, human-heavy ratios** — 96.9% on a 95%-human social mix with
~1% human false-positives — because with no graph the over-connection flag can't
fire. Its weakness is the mirror image: ~39% sybil recall. So scoring v2 should
target **batch's human false-positive rate** (raise recall without wrecking
humans), while single mode already serves the real-time path well; the near-term
answer is the **hybrid** pattern ([`hybrid-integration.md`](hybrid-integration.md)),
not a scoring change. Full numbers: [`accuracy-gap.md`](accuracy-gap.md).

## Fix 1 — `CLUSTER_MIN_SIGNALS: 1 → 2`  ✅ SHIPPED in v0.5.0-threshold-v2 (2026-08-10)

Require two graph signals so `cluster_size` alone can't trip the flag.

- **Measured:** balanced 54.2% → 62.5% (+8.3 pts); human false-positives
  8/12 → 5/12; held-out TEST unchanged; sybil recall 75% → 67%; TRAIN −5.2 pts.
- **Verdict:** real but modest; **narrows, does not close** the gap. Low-risk
  (no held-out-test regression).
- **Shipped:** `CLUSTER_MIN_SIGNALS` now defaults to `2`; `SCORER_VERSION` bumped
  to `0.5.0-threshold-v2` (old history keeps `0.4.0-graph`); scoring tests
  updated to the new default; `SCORING_CLUSTER_MIN_SIGNALS=1` still reproduces
  the old behavior. Post-ship verification reproduced the numbers exactly.

## Fix 2 — rare-counterparty edge filtering  ⚠️ ATTEMPTED → REVERTED (negative result)

Implemented as a blanket "drop counterparties touching >20% of wallets" filter
behind `RARE_COUNTERPARTY_FILTER_ENABLED` (default off; code retained). Result:
improved holdout TEST +3.6 pts but did **not** improve the balanced set, and a
degree-only filter risks removing genuine farming-funder signal (sybil-recall
collapse concern). **Reverted** — see `scoring-v2-experiment-log.md`. Production
stays `0.5.0-threshold-v2`.

Redesign for a future attempt: don't filter on degree alone. Distinguish
**infra** (0% inbound, contract — safe to drop) from **funders** (inbound EOA —
must keep), or **down-weight** rather than hard-drop, so `cluster_size` stops
over-connecting without erasing shared-funder signal.

## Fix 3 — cluster-aligned batching  (product/integration, not scoring)

Graph features only discriminate on a meaningful neighborhood. Batch wallets
that plausibly belong together (same campaign / referrer / signup time window),
not a random mix, so `/verify/batch` sees real structure. This is a client-side
batching policy (see [`hybrid-integration.md`](hybrid-integration.md)), not a
scoring change.

## Fix 4 — grow + balance the labeled set, re-evaluate on a balanced holdout  ✅ DONE (Week 12)

The 78.6% headline is **Sybil-dominated** (`scoring-eval.md`'s own caveat), which
inflates it relative to real-world balanced performance. Add independent human +
sybil clusters from more projects, and report a **balanced** held-out accuracy as
the headline so tuning targets real discrimination, not the class prior.

**Done (Week 12).** The evaluation pool was expanded from 24 to **246 wallets** —
105 existing + 141 newly collected, Etherscan-verified, non-contract wallets (92
Snapshot governance-voter humans + 49 official Optimism sybils). It was used for
evaluation only and **not merged** into production `labeled_wallets.json`
([`labeled-dataset-v2.md`](labeled-dataset-v2.md)). What it revealed, on the
**unchanged** `v0.5.0` scorer (`human_likelihood` primary metric, live-verified
2026-08-18):

- **Balanced 50/50:** batch **68.3%** / recall 79.2% / **42.5% human FP**; single
  **69.2%** / recall 39.2% / **0.8% human FP**.
- **Social 95/5:** batch 58.6% (40.6% of all users wrongly flagged); single
  **96.9%** (0.8% human FP).
- **Airdrop 30/70:** batch **72.9%** / recall 79.8%; single 57.1% / recall 39.5%.

This is a **dataset** change, not a scoring gain — the two-mode tradeoff and the
hybrid recommendation ([`accuracy-gap.md`](accuracy-gap.md),
[`final-presentation.md`](final-presentation.md)) are the real deliverable. A
balanced held-out re-tune (the remaining part of this fix) is still future work.

## Suggested order

1. Fix 2 (biggest lever, root cause) → re-measure balanced + holdout.
2. Re-evaluate Fix 1's threshold *after* Fix 2 (it may no longer be needed, or
   the right value may differ — re-tune only against a balanced holdout).
3. Fix 4 (data) in parallel, to make every number above trustworthy.
4. Fix 3 on the integration side, independent of the above.

Each change must be measured single-variable with red lines and an ablation, as
in `threshold-experiment.md` — no multi-knob tuning to chase a number.

## Reference existing work

Sybil-detection / anti-abuse systems reviewed during the internship, as
reference points for a future scoring v2. **None of their code is integrated** —
this is a comparison for design ideas only.

### 1. Gitcoin Passport — <https://github.com/gitcoinco/passport>
- **Approach:** Aggregates opt-in, off-chain "stamps" (verifiable credentials from
  Google, X/Twitter, ENS, BrightID, POAP, etc.) into a single humanity/uniqueness
  score.
- **Why not directly applicable:** It scores *credentials the user chose to
  attach*, not passive on-chain behavior; it needs user action and off-chain
  integrations we don't have, and it answers "did you prove humanity" rather than
  "does this wallet's activity look like farming."
- **Learn for v2:** the weighted-composite-of-many-weak-signals model with a
  tunable acceptance threshold, and score expiry/decay — closer to a reputation
  score than a binary flag.

### 2. Chainalysis Reactor — <https://www.chainalysis.com/> (Reactor product)
- **Approach:** Commercial blockchain-forensics tool that clusters addresses into
  real-world entities (exchanges, mixers, illicit actors) using proprietary
  heuristics plus a large proprietary labeled dataset, mainly for AML /
  investigations.
- **Why not directly applicable:** closed-source, paid, and aimed at entity
  attribution / illicit-fund tracing, not airdrop-sybil-farming; it's incompatible
  with our transparent, auditable, rule-based design (we can't inspect or
  reproduce its heuristics).
- **Learn for v2:** entity clustering via co-funding / co-spending heuristics, and
  the outsized value of a high-quality labeled entity set (which our small dataset
  lacks) — including cleanly separating contract/exchange/bridge addresses from
  user EOAs (we already do a contract filter).

### 3. SybilRank / academic trust-propagation — Cao et al., *Aiding the Detection of Fake Accounts in Large Scale Social Online Services*, USENIX NSDI 2012 (related: SybilGuard, SybilLimit, EigenTrust)
- **Approach:** Seed trust at a small set of known-honest nodes and propagate it
  via short random walks / power iteration over the trust graph, ranking a node
  low if it sits behind a sparse "attack cut" from the honest region.
- **Why not directly applicable:** it assumes a fast-mixing honest social graph
  with few attack edges — a *financial* transaction graph violates this (everyone
  transacts with the same DEXs/stablecoins, so there is no sparse honest/sybil
  cut — precisely the over-connection we measured in Week 11 and in Experiment 1).
  It also needs a maintained trusted seed set.
- **Learn for v2:** seed-based trust propagation from a known-honest anchor set
  (e.g. our verified governance voters) instead of unsupervised clustering;
  measuring *connectivity to honest anchors* rather than raw `cluster_size`; and
  random-walk / conductance signals that are more robust to shared-infra edges.

### 4. Optimism sybil filter — official excluded-address list + methodology note in `ethereum-optimism/community-hub` (airdrop-1); list published as a public Google Sheet (accessed for our dataset v2)
- **Approach:** Combined automated on-chain activity heuristics (categorized in the
  published list as "L1 Activity" / "L2 Activity") with "Community Reports" to
  remove ~17k addresses; the *exact* filter logic was deliberately not published.
- **Why not directly applicable:** the methodology is intentionally opaque (to
  prevent gaming), so it isn't reproducible; it's a one-time batch airdrop filter,
  not a continuous real-time score; and it leans on multi-chain (OP + L1) signals
  we only partially ingest.
- **Learn for v2:** pairing automated heuristics with a community-report channel
  (human-in-the-loop labels); multi-chain activity as a signal; and the explicit
  transparency-vs-gameability tradeoff — Optimism chose opacity, we deliberately
  chose transparency/auditability, so we must assume our published rules will be
  gamed and design for it.

### 5. LayerZero sybil report — official Medium: <https://medium.com/layerzero-official/addressing-sybil-activity-a2f92218ddd3> (the address repo `LayerZero-Labs/sybil-report` is now 404)
- **Approach:** A self-report phase (sybils self-declare in exchange for 15% of
  their allocation) plus independent analysis by LayerZero + Chaos Labs + Nansen,
  identifying ~803k addresses via clustering across the combined signals.
- **Why not directly applicable:** it relies on an economic self-report incentive
  and third-party proprietary analytics (Nansen/Chaos) we can't run; the output is
  a static bulk list, not a scoring method; and it isn't reproducible by us.
- **Learn for v2:** the self-report incentive as a *labeling* mechanism (economic
  design to surface ground truth); ensembling multiple independent detectors
  rather than a single rule engine; and a sober sense of scale (~800k sybils) for
  what real detection faces.
