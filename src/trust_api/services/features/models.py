"""DTO for the computed per-wallet behavioral features (Week 3)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class WalletFeatures:
    """The 10 behavioral features computed from a wallet's transactions."""

    wallet_id: int
    chain: str
    wallet_age_days: int
    tx_count: int
    active_days: int
    tx_per_active_day: float
    counterparty_count: int
    counterparty_diversity_ratio: float
    inbound_ratio: float
    burst_score: int
    dormancy_flag: bool
    recency_days: int
    computed_at: datetime | None = None
