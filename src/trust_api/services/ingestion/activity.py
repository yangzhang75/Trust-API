"""Deterministic activity stub (the Week 1 behavior, preserved).

`fetch_activity` feeds the still-stubbed features/scoring stages and keeps
the /verify pipeline deterministic and offline. Real ingestion (provider +
ETL + persistence) lives alongside this in the same package and is driven
by the background worker / seed script, not by /verify.
"""

from __future__ import annotations

import hashlib

from trust_api.schemas.verify import Chain
from trust_api.services.ingestion.models import WalletActivity


def _wallet_seed(wallet: str) -> int:
    """Stable 64-bit seed derived from the (lowercased) wallet address."""
    digest = hashlib.sha256(wallet.lower().encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big")


def fetch_activity(wallet: str, chains: list[Chain]) -> WalletActivity:
    """Return a deterministic activity summary for ``wallet``.

    TODO(week3+): derive features from the persisted, real transaction
    history (services.ingestion.service) instead of this hash-based stub.
    """
    seed = _wallet_seed(wallet)
    return WalletActivity(
        wallet=wallet,
        chains=tuple(chains),
        seed=seed,
        tx_count=seed % 5000,
        account_age_days=seed % 2000,
        unique_counterparties=seed % 800,
    )
