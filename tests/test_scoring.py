"""Unit tests for the (stubbed) scoring stage — tier + risk-flag logic."""

from __future__ import annotations

from trust_api.schemas.verify import HumanLikelihood, RiskFlag, TrustTier
from trust_api.services.features import WalletFeatures
from trust_api.services.scoring import score


def test_high_scores_map_to_gold_high_no_flags() -> None:
    assessment = score(WalletFeatures(activity_score=1.0, age_score=1.0, diversity_score=1.0))
    assert assessment.confidence_score == 1.0
    assert assessment.human_likelihood is HumanLikelihood.high
    assert assessment.trust_tier is TrustTier.gold
    assert assessment.risk_flags == []


def test_mid_scores_map_to_silver_medium() -> None:
    assessment = score(WalletFeatures(activity_score=0.5, age_score=0.5, diversity_score=0.5))
    assert assessment.human_likelihood is HumanLikelihood.medium
    assert assessment.trust_tier is TrustTier.silver
    assert assessment.risk_flags == []


def test_low_scores_map_to_bronze_low_with_all_flags() -> None:
    assessment = score(WalletFeatures(activity_score=0.0, age_score=0.0, diversity_score=0.0))
    assert assessment.confidence_score == 0.0
    assert assessment.human_likelihood is HumanLikelihood.low
    assert assessment.trust_tier is TrustTier.bronze
    assert set(assessment.risk_flags) == {
        RiskFlag.new_wallet,
        RiskFlag.low_activity,
        RiskFlag.low_counterparty_diversity,
        RiskFlag.sybil_suspected,
    }
