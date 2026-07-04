"""Unit tests for the rule-based scoring engine."""

from __future__ import annotations

from trust_api.schemas.verify import HumanLikelihood, RiskFlag, TrustTier
from trust_api.services.features import WalletFeatures
from trust_api.services.scoring import config, engine, score


def _features(**overrides) -> WalletFeatures:
    """A strong 'human' baseline; override fields to exercise specific rules."""
    base = dict(
        wallet_id=1,
        chain="ethereum",
        wallet_age_days=800,
        tx_count=500,
        active_days=120,
        tx_per_active_day=4.0,
        counterparty_count=300,
        counterparty_diversity_ratio=0.6,
        inbound_ratio=0.5,
        burst_score=3,
        dormancy_flag=False,
        recency_days=1,
    )
    base.update(overrides)
    return WalletFeatures(**base)


# --- individual rules -----------------------------------------------------


def test_rule_new_wallet() -> None:
    assert engine.rule_new_wallet(_features(wallet_age_days=10)) is True
    assert engine.rule_new_wallet(_features(wallet_age_days=30)) is False


def test_rule_low_activity() -> None:
    assert engine.rule_low_activity(_features(tx_count=4)) is True
    assert engine.rule_low_activity(_features(tx_count=5)) is False


def test_rule_low_diversity() -> None:
    assert engine.rule_low_diversity(_features(counterparty_diversity_ratio=0.05)) is True
    assert engine.rule_low_diversity(_features(counterparty_diversity_ratio=0.10)) is False


def test_rule_bot_burst() -> None:
    assert engine.rule_bot_burst(_features(burst_score=21)) is True
    assert engine.rule_bot_burst(_features(burst_score=20)) is False


def test_rule_dormant() -> None:
    assert engine.rule_dormant(_features(dormancy_flag=True)) is True
    assert engine.rule_dormant(_features(dormancy_flag=False)) is False


def test_none_values_treated_as_zero() -> None:
    # ORM rows can carry NULLs; rules must not crash.
    assert engine.rule_new_wallet(_features(wallet_age_days=None)) is True
    assert engine.positive_score(_features(tx_count=None, wallet_age_days=None)) >= 0.0


# --- risk flag combinations ----------------------------------------------


def test_strong_human_has_no_flags() -> None:
    assert engine.risk_flags(_features()) == []


def test_sybil_suspected_when_multiple_signals() -> None:
    # low diversity + bot burst = 2 signals -> sybil_suspected
    flags = engine.risk_flags(_features(counterparty_diversity_ratio=0.01, burst_score=50))
    assert RiskFlag.sybil_suspected in flags
    assert RiskFlag.low_counterparty_diversity in flags
    assert RiskFlag.bot_burst in flags


def test_single_signal_is_not_sybil() -> None:
    flags = engine.risk_flags(_features(burst_score=50))  # only one signal
    assert RiskFlag.sybil_suspected not in flags


# --- bucketing ------------------------------------------------------------


def test_bucketing_thresholds() -> None:
    assert config.likelihood_for(0.75) is HumanLikelihood.high
    assert config.likelihood_for(0.74) is HumanLikelihood.medium
    assert config.likelihood_for(0.40) is HumanLikelihood.medium
    assert config.likelihood_for(0.39) is HumanLikelihood.low
    assert config.tier_for(0.75) is TrustTier.gold
    assert config.tier_for(0.40) is TrustTier.silver
    assert config.tier_for(0.39) is TrustTier.bronze


# --- end-to-end scoring ---------------------------------------------------


def test_strong_human_scores_high_gold() -> None:
    r = score(_features())
    assert r.human_likelihood is HumanLikelihood.high
    assert r.trust_tier is TrustTier.gold
    assert r.confidence_score >= 0.75
    assert r.risk_flags == []


def test_empty_wallet_scores_low_bronze_with_flags() -> None:
    r = score(
        _features(
            wallet_age_days=0,
            tx_count=0,
            active_days=0,
            counterparty_diversity_ratio=0.0,
            burst_score=0,
        )
    )
    assert r.human_likelihood is HumanLikelihood.low
    assert r.trust_tier is TrustTier.bronze
    assert r.confidence_score == 0.0
    assert RiskFlag.new_wallet in r.risk_flags
    assert RiskFlag.low_activity in r.risk_flags
    assert RiskFlag.sybil_suspected in r.risk_flags


def test_confidence_clamped_and_deterministic() -> None:
    f = _features(wallet_age_days=15, tx_count=3, counterparty_diversity_ratio=0.01, burst_score=50)
    first = score(f)
    second = score(f)
    assert 0.0 <= first.confidence_score <= 1.0
    assert first == second  # same input -> same output
