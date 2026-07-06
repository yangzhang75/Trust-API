"""Scoring configuration — all thresholds, weights, and buckets in ONE place.

Week 4 scoring is deliberately rule-based and transparent. Every number a
wallet's score depends on lives here so it can be tuned and audited in a
single file. See docs/scoring.md for the human-readable rationale.
"""

from __future__ import annotations

from trust_api.schemas.verify import HumanLikelihood, RiskFlag, TrustTier

# --- Risk-rule thresholds -------------------------------------------------
NEW_WALLET_MAX_AGE_DAYS = 30  # younger than this -> new_wallet
LOW_ACTIVITY_MAX_TX = 5  # fewer than this many txs -> low_activity
LOW_DIVERSITY_MAX_RATIO = 0.10  # counterparty diversity below this -> flag
BOT_BURST_MIN_TX_PER_HOUR = 20  # more than this in one hour -> bot_burst
# sybil_suspected fires when at least this many independent Sybil-ish
# signals are present at once (see engine._sybil_signals).
SYBIL_MIN_SIGNALS = 2

# --- Graph / cluster thresholds (Week 4 "B"; a-priori, NOT tuned to data) --
SHARED_FUNDER_MIN = 0.33  # >= 1 of top-3 funders shared with another wallet
COUNTERPARTY_OVERLAP_MIN = 0.30  # Jaccard overlap with another wallet
FUNDING_CHAIN_MIN = 2  # relay depth: funded through >= 2 in-sample hops
CLUSTER_SIZE_MIN = 3  # connected component of >= 3 wallets
# sybil_cluster fires when at least this many graph signals are present.
CLUSTER_MIN_SIGNALS = 1

# --- Positive-evidence saturation points ----------------------------------
# Each positive sub-score is feature / full-credit-point, capped at 1.0.
AGE_FULL_DAYS = 365  # >= 1 year of history -> full age credit
ACTIVITY_FULL_TX = 100  # >= 100 transactions -> full activity credit
DIVERSITY_FULL_RATIO = 0.50  # >= 0.5 diversity -> full diversity credit
ACTIVE_DAYS_FULL = 60  # >= 60 active days -> full consistency credit

# --- Positive-evidence weights (sum to 1.0) -------------------------------
W_AGE = 0.30
W_ACTIVITY = 0.30
W_DIVERSITY = 0.25
W_ACTIVE_DAYS = 0.15

# --- Penalties subtracted from the positive score per fired risk flag -----
RISK_PENALTIES: dict[RiskFlag, float] = {
    RiskFlag.new_wallet: 0.15,
    RiskFlag.low_activity: 0.20,
    RiskFlag.low_counterparty_diversity: 0.20,
    RiskFlag.bot_burst: 0.25,
    RiskFlag.dormant: 0.10,
    RiskFlag.sybil_suspected: 0.30,
    RiskFlag.sybil_cluster: 0.35,
}

# --- Confidence buckets ---------------------------------------------------
HIGH_MIN = 0.75  # confidence >= 0.75 -> high / gold
MEDIUM_MIN = 0.40  # 0.40 <= confidence < 0.75 -> medium / silver
# below MEDIUM_MIN -> low / bronze


def likelihood_for(confidence: float) -> HumanLikelihood:
    if confidence >= HIGH_MIN:
        return HumanLikelihood.high
    if confidence >= MEDIUM_MIN:
        return HumanLikelihood.medium
    return HumanLikelihood.low


def tier_for(confidence: float) -> TrustTier:
    if confidence >= HIGH_MIN:
        return TrustTier.gold
    if confidence >= MEDIUM_MIN:
        return TrustTier.silver
    return TrustTier.bronze
