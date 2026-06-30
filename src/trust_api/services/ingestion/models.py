"""Internal DTOs for the ingestion subsystem.

`Transaction` is the normalized record produced by the ETL transform step;
`WalletActivity` is the coarse, privacy-preserving summary the downstream
features stage consumes (unchanged from Week 1).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from trust_api.schemas.verify import Chain


@dataclass(frozen=True)
class Transaction:
    """A normalized on-chain transaction for one wallet+chain.

    Internal only — never serialized to the public API.
    """

    chain: Chain
    tx_hash: str
    block_number: int
    block_time: datetime
    value_wei: int
    direction: str  # "in" | "out" | "self"
    counterparty: str


@dataclass(frozen=True)
class WalletActivity:
    """Coarse, privacy-preserving activity summary (internal DTO).

    Never carries raw transaction data downstream.
    """

    wallet: str
    chains: tuple[Chain, ...]
    seed: int
    tx_count: int
    account_age_days: int
    unique_counterparties: int
