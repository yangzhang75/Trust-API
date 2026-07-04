"""Internal DTO for the ingestion subsystem.

`Transaction` is the normalized record produced by the ETL transform step.
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
