"""Deterministic activity-feature stub (the Week 1 behavior, preserved).

Feeds the still-stubbed scoring stage so /verify stays deterministic and
offline. The REAL behavioral features (Week 3) live in service.py and are
computed from the database.
"""

from __future__ import annotations

from dataclasses import dataclass

from trust_api.services.ingestion import WalletActivity


@dataclass(frozen=True)
class ActivityFeatures:
    """Normalized [0, 1] activity scores feeding the stub scoring model."""

    activity_score: float
    age_score: float
    diversity_score: float


def compute_activity_features(activity: WalletActivity) -> ActivityFeatures:
    """Compute normalized activity scores from a (stub) activity summary."""
    return ActivityFeatures(
        activity_score=min(activity.tx_count / 5000.0, 1.0),
        age_score=min(activity.account_age_days / 2000.0, 1.0),
        diversity_score=min(activity.unique_counterparties / 800.0, 1.0),
    )
