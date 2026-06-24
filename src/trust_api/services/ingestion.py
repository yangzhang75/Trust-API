"""Ingestion service — fetches raw on-chain activity for a wallet.

Week 1 is a STUB: it returns deterministic synthetic activity derived
from a hash of the wallet address so downstream stages (and tests) are
stable. No real RPC/indexer calls are made.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from trust_api.schemas.verify import Chain


@dataclass(frozen=True)
class WalletActivity:
    """Normalized on-chain activity for a wallet (internal DTO).

    Intentionally coarse for Week 1 — never carries raw transaction data.
    """

    wallet: str
    chains: tuple[Chain, ...]
    seed: int
    tx_count: int
    account_age_days: int
    unique_counterparties: int


def _wallet_seed(wallet: str) -> int:
    """Stable 64-bit seed derived from the (lowercased) wallet address."""
    digest = hashlib.sha256(wallet.lower().encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big")


def fetch_activity(wallet: str, chains: list[Chain]) -> WalletActivity:
    """Return on-chain activity for ``wallet``.

    TODO(week2): replace the stub with real ingestion (RPC providers /
    indexers such as Alchemy, Etherscan, or a self-hosted node), with
    per-chain adapters and caching in Redis.
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
