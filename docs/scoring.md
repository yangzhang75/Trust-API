# Trust Scoring (Week 4)

This document explains **exactly** how a wallet's trust score is produced.
The scorer is deliberately **rule-based, transparent, and deterministic** —
no machine learning. Given a wallet you can point at which rules fired and
how the number was reached. Every threshold and weight below lives in one
file: `src/trust_api/services/scoring/config.py`.

Inputs are the 10 behavioral features from [`features.md`](features.md).
The output is: `human_likelihood` (high/medium/low), `trust_tier`
(gold/silver/bronze), `confidence_score` (0–1), and `risk_flags`.

## How the score is built

1. **Positive evidence** — a weighted score in 0–1 that grows with signs of
   a real, organic human. Each part saturates at a "full credit" point.

   | Signal | Full credit at | Weight |
   | --- | --- | --- |
   | Wallet age | ≥ 365 days | 0.30 |
   | Activity (tx count) | ≥ 100 txs | 0.30 |
   | Counterparty diversity | ≥ 0.50 ratio | 0.25 |
   | Consistency (active days) | ≥ 60 days | 0.15 |

   e.g. a wallet 180 days old gets `180/365 = 0.49` of the age weight.

2. **Risk penalties** — each risk flag that fires subtracts from the score:

   | Risk flag | Fires when | Penalty |
   | --- | --- | --- |
   | `new_wallet` | age < 30 days | 0.15 |
   | `low_activity` | tx count < 5 | 0.20 |
   | `low_counterparty_diversity` | diversity ratio < 0.10 | 0.20 |
   | `bot_burst` | > 20 txs in a single hour | 0.25 |
   | `dormant` | inactive > 90 days | 0.10 |
   | `sybil_suspected` | ≥ 2 Sybil signals at once (see below) | 0.30 |

   **Sybil signal set:** `low_counterparty_diversity`, `bot_burst`, and
   (`new_wallet` **and** `low_activity`). If at least 2 of these are true,
   `sybil_suspected` fires.

3. **Confidence** = `positive_evidence − sum(penalties)`, clamped to
   `[0, 1]` and rounded to 4 decimals.

4. **Buckets** (same thresholds for likelihood and tier):

   | Confidence | human_likelihood | trust_tier |
   | --- | --- | --- |
   | ≥ 0.75 | high | gold |
   | 0.40 – 0.75 | medium | silver |
   | < 0.40 | low | bronze |

## Worked examples

- **Long-lived active human:** age 800d, 500 txs, diversity 0.6, 120 active
  days → positive ≈ 1.0, no flags → confidence ≈ 1.0 → **high / gold**.
- **Fresh farming wallet:** age 2d, 1 tx, diversity 0.0 → flags
  `new_wallet`, `low_activity`, `low_counterparty_diversity`,
  `sybil_suspected`; positive ≈ 0 → confidence 0.0 → **low / bronze**.

## Why rule-based (not ML)

ML would be premature without a much larger, balanced, verified labeled
set — it would look accurate on a tiny dataset and fail in the wild, and it
would be a black box. Rules are auditable and tunable in one file. The
current accuracy and honest limitations are tracked in
[`scoring-eval.md`](scoring-eval.md); ML is a later-stage option once the
labeled dataset is large enough to justify it.

## Tuning

Change any number in `scoring/config.py` and re-run
`python -m trust_api.jobs.evaluate_scoring` to see the effect on the
labeled dataset. Nothing else needs to change.
