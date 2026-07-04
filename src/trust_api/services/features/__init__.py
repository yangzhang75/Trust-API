"""Feature subsystem — real per-wallet behavioral features (Week 3).

`WalletFeatures` + `compute_features` compute features from
wallet_transactions and store them in wallet_features; the scoring engine
consumes them.
"""

from __future__ import annotations

from trust_api.services.features.models import WalletFeatures
from trust_api.services.features.service import (
    all_wallet_ids_with_transactions,
    compute_features,
    compute_features_for_wallets,
)

__all__ = [
    "WalletFeatures",
    "all_wallet_ids_with_transactions",
    "compute_features",
    "compute_features_for_wallets",
]
