"""Feature subsystem.

- `ActivityFeatures` / `compute_activity_features` — the deterministic stub
  feeding the still-stubbed scoring stage (Week 1 behavior, unchanged).
- `WalletFeatures` + `compute_features` — the real Week 3 behavioral
  features computed from wallet_transactions and stored in wallet_features.
"""

from __future__ import annotations

from trust_api.services.features.models import WalletFeatures
from trust_api.services.features.service import (
    all_wallet_ids_with_transactions,
    compute_features,
    compute_features_for_wallets,
)
from trust_api.services.features.stub import ActivityFeatures, compute_activity_features

__all__ = [
    "ActivityFeatures",
    "WalletFeatures",
    "all_wallet_ids_with_transactions",
    "compute_activity_features",
    "compute_features",
    "compute_features_for_wallets",
]
