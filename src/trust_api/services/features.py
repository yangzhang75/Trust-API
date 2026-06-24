"""Feature service — derives model features from raw activity.

Week 1 is a STUB: features are simple deterministic transforms of the
synthetic activity. Real feature engineering arrives later.
"""

from __future__ import annotations

from dataclasses import dataclass

from trust_api.services.ingestion import WalletActivity


@dataclass(frozen=True)
class WalletFeatures:
    """Normalized [0, 1] features feeding the scoring model (internal DTO)."""

    activity_score: float
    age_score: float
    diversity_score: float


def compute_features(activity: WalletActivity) -> WalletFeatures:
    """Compute normalized features from ``activity``.

    TODO(week3): real feature engineering (temporal patterns, gas profiles,
    contract-interaction graphs, funding-source lineage) persisted to the
    wallet_features table.
    """
    return WalletFeatures(
        activity_score=min(activity.tx_count / 5000.0, 1.0),
        age_score=min(activity.account_age_days / 2000.0, 1.0),
        diversity_score=min(activity.unique_counterparties / 800.0, 1.0),
    )
