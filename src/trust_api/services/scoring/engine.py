"""Transparent, rule-based scoring engine (Week 4).

Deterministic and inspectable: given a wallet's features you can point at
exactly which rules fired and how the weighted positive evidence and risk
penalties combined into the confidence score. No ML. All numbers come from
scoring.config. Accepts the WalletFeatures DTO or the WalletFeature ORM row
(same attribute names); None values are treated as 0.
"""

from __future__ import annotations

from typing import Any

from trust_api.schemas.verify import RiskFlag
from trust_api.services.scoring import config
from trust_api.services.scoring.models import ScoringResult

# --- Individual rules (each testable in isolation) ------------------------


def rule_new_wallet(f: Any) -> bool:
    return (f.wallet_age_days or 0) < config.NEW_WALLET_MAX_AGE_DAYS


def rule_low_activity(f: Any) -> bool:
    return (f.tx_count or 0) < config.LOW_ACTIVITY_MAX_TX


def rule_low_diversity(f: Any) -> bool:
    return (f.counterparty_diversity_ratio or 0.0) < config.LOW_DIVERSITY_MAX_RATIO


def rule_bot_burst(f: Any) -> bool:
    return (f.burst_score or 0) > config.BOT_BURST_MIN_TX_PER_HOUR


def rule_dormant(f: Any) -> bool:
    return bool(f.dormancy_flag)


def _sybil_signals(f: Any) -> int:
    """Count independent Sybil-ish signals present at once."""
    return sum(
        [
            rule_low_diversity(f),
            rule_bot_burst(f),
            rule_new_wallet(f) and rule_low_activity(f),
        ]
    )


def risk_flags(f: Any) -> list[RiskFlag]:
    """Return every risk flag that fires for ``f`` (order is stable)."""
    flags: list[RiskFlag] = []
    if rule_new_wallet(f):
        flags.append(RiskFlag.new_wallet)
    if rule_low_activity(f):
        flags.append(RiskFlag.low_activity)
    if rule_low_diversity(f):
        flags.append(RiskFlag.low_counterparty_diversity)
    if rule_bot_burst(f):
        flags.append(RiskFlag.bot_burst)
    if rule_dormant(f):
        flags.append(RiskFlag.dormant)
    if _sybil_signals(f) >= config.SYBIL_MIN_SIGNALS:
        flags.append(RiskFlag.sybil_suspected)
    return flags


def positive_score(f: Any) -> float:
    """Weighted positive evidence that the wallet is a real human, in [0, 1]."""
    age = min((f.wallet_age_days or 0) / config.AGE_FULL_DAYS, 1.0)
    activity = min((f.tx_count or 0) / config.ACTIVITY_FULL_TX, 1.0)
    diversity = min((f.counterparty_diversity_ratio or 0.0) / config.DIVERSITY_FULL_RATIO, 1.0)
    consistency = min((f.active_days or 0) / config.ACTIVE_DAYS_FULL, 1.0)
    return (
        config.W_AGE * age
        + config.W_ACTIVITY * activity
        + config.W_DIVERSITY * diversity
        + config.W_ACTIVE_DAYS * consistency
    )


def score(features: Any) -> ScoringResult:
    """Score a wallet's features into a trust assessment (pure, deterministic)."""
    flags = risk_flags(features)
    base = positive_score(features)
    penalty = sum(config.RISK_PENALTIES[flag] for flag in flags)
    confidence = round(max(0.0, min(1.0, base - penalty)), 4)
    return ScoringResult(
        human_likelihood=config.likelihood_for(confidence),
        trust_tier=config.tier_for(confidence),
        confidence_score=confidence,
        risk_flags=flags,
    )
