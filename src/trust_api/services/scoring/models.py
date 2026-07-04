"""Scoring result DTO."""

from __future__ import annotations

from dataclasses import dataclass

from trust_api.schemas.verify import HumanLikelihood, RiskFlag, TrustTier


@dataclass(frozen=True)
class ScoringResult:
    """The outcome of scoring a wallet's features."""

    human_likelihood: HumanLikelihood
    trust_tier: TrustTier
    confidence_score: float
    risk_flags: list[RiskFlag]
