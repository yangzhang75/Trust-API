"""Scoring service — turns features into a trust assessment.

Week 1 is a STUB: a transparent weighted average plus threshold buckets,
fully deterministic given the wallet. No ML, no Sybil detection.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from trust_api.core.logging import get_logger
from trust_api.schemas.verify import HumanLikelihood, RiskFlag, TrustTier
from trust_api.services.features import ActivityFeatures

logger = get_logger(__name__)


@dataclass(frozen=True)
class TrustAssessment:
    """The scored outcome for a wallet (internal DTO)."""

    human_likelihood: HumanLikelihood
    trust_tier: TrustTier
    confidence_score: float
    risk_flags: list[RiskFlag]


def score(features: ActivityFeatures, stored_features: Any | None = None) -> TrustAssessment:
    """Score ``features`` into a trust assessment.

    ``stored_features`` is the real wallet_features row when the wallet has
    been ingested. Week 3 only proves the plumbing (ingestion -> features ->
    scoring) — the output stays a deterministic STUB regardless.

    TODO(week4): replace with the real scoring model (calibrated ML /
    heuristic ensemble) that actually consumes stored_features, plus a
    dedicated Sybil-detection stage; persist to the trust_scores table.
    """
    if stored_features is not None:
        logger.debug(
            "scoring wallet_id=%s from stored features (still stub output)",
            stored_features.wallet_id,
        )
    confidence = round(
        0.4 * features.activity_score + 0.3 * features.age_score + 0.3 * features.diversity_score,
        4,
    )

    if confidence >= 0.7:
        likelihood, tier = HumanLikelihood.high, TrustTier.gold
    elif confidence >= 0.4:
        likelihood, tier = HumanLikelihood.medium, TrustTier.silver
    else:
        likelihood, tier = HumanLikelihood.low, TrustTier.bronze

    flags: list[RiskFlag] = []
    if features.age_score < 0.2:
        flags.append(RiskFlag.new_wallet)
    if features.activity_score < 0.2:
        flags.append(RiskFlag.low_activity)
    if features.diversity_score < 0.2:
        flags.append(RiskFlag.low_counterparty_diversity)
    # TODO(week4): real Sybil clustering; stubbed as a low-confidence signal.
    if confidence < 0.25:
        flags.append(RiskFlag.sybil_suspected)

    return TrustAssessment(
        human_likelihood=likelihood,
        trust_tier=tier,
        confidence_score=confidence,
        risk_flags=flags,
    )
