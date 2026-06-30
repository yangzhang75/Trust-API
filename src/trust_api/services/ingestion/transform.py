"""ETL transform step: normalize raw provider rows into Transactions.

Pure and side-effect-free so it is trivially unit-testable. Malformed rows
are skipped rather than crashing the whole ingestion.
"""

from __future__ import annotations

from datetime import UTC, datetime

from trust_api.core.logging import get_logger
from trust_api.schemas.verify import Chain
from trust_api.services.ingestion.models import Transaction

logger = get_logger(__name__)


def _classify(wallet: str, frm: str, to: str, contract: str) -> tuple[str, str | None]:
    """Return (direction, counterparty) relative to ``wallet`` (lowercased)."""
    if frm == wallet and to == wallet:
        return "self", wallet
    if frm == wallet:
        # Contract-creation tx has an empty `to`; use the created address.
        return "out", (to or contract or None)
    if to == wallet:
        return "in", frm
    # Shouldn't happen for a single-address txlist; skip upstream.
    return "out", (to or None)


def normalize_transactions(raw: list[dict], wallet: str, chain: Chain) -> list[Transaction]:
    """Normalize Etherscan `txlist` rows into Transaction DTOs."""
    wallet_l = wallet.lower()
    out: list[Transaction] = []
    for row in raw:
        try:
            frm = str(row.get("from", "")).lower()
            to = str(row.get("to", "")).lower()
            contract = str(row.get("contractAddress", "")).lower()
            # Only rows that actually involve the wallet are meaningful.
            if wallet_l not in (frm, to):
                continue
            direction, counterparty = _classify(wallet_l, frm, to, contract)
            out.append(
                Transaction(
                    chain=chain,
                    tx_hash=str(row["hash"]),
                    block_number=int(row["blockNumber"]),
                    block_time=datetime.fromtimestamp(int(row["timeStamp"]), tz=UTC),
                    value_wei=int(row["value"]),
                    direction=direction,
                    counterparty=counterparty,
                )
            )
        except (KeyError, ValueError, TypeError) as exc:
            logger.warning("skipping malformed tx row: %s", exc)
            continue
    return out
