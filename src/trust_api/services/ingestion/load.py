"""ETL load step: idempotent upsert of transactions into Postgres.

Re-running ingestion for the same wallet must not create duplicate rows —
enforced by ON CONFLICT DO NOTHING against the (wallet_id, tx_hash) unique
constraint. Wallet-level aggregates (first_seen/last_seen/tx_count) are
recomputed from the stored rows after each load.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from trust_api.db.models import Wallet, WalletTransaction
from trust_api.schemas.verify import Chain
from trust_api.services.ingestion.models import Transaction


@dataclass(frozen=True)
class LoadResult:
    """Outcome of loading a batch of transactions for a wallet."""

    wallet_id: int
    inserted: int  # rows newly inserted this run (0 on a pure re-run)
    total: int  # total stored rows for the wallet after the load


def _get_or_create_wallet(session: Session, address: str) -> Wallet:
    wallet = session.execute(select(Wallet).where(Wallet.address == address)).scalar_one_or_none()
    if wallet is None:
        wallet = Wallet(address=address)
        session.add(wallet)
        session.flush()  # assign id
    return wallet


def load_transactions(
    session: Session, address: str, chain: Chain, txs: list[Transaction]
) -> LoadResult:
    """Idempotently persist ``txs`` for ``address`` and refresh aggregates."""
    wallet = _get_or_create_wallet(session, address)

    inserted = 0
    if txs:
        # De-duplicate within the batch: a provider can return the same
        # tx_hash more than once (pagination overlap / internal entries).
        # The DB unique constraint handles cross-run dupes; this handles
        # in-batch ones so the insert and the `inserted` count stay correct.
        unique: dict[str, Transaction] = {}
        for tx in txs:
            unique.setdefault(tx.tx_hash, tx)
        rows = [
            {
                "wallet_id": wallet.id,
                "chain": str(tx.chain),
                "tx_hash": tx.tx_hash,
                "block_number": tx.block_number,
                "block_time": tx.block_time,
                "value_wei": tx.value_wei,
                "direction": tx.direction,
                "counterparty": tx.counterparty,
            }
            for tx in unique.values()
        ]
        stmt = (
            pg_insert(WalletTransaction)
            .values(rows)
            .on_conflict_do_nothing(index_elements=["wallet_id", "tx_hash"])
            .returning(WalletTransaction.id)
        )
        # RETURNING yields only the rows actually inserted (skips conflicts),
        # which is reliable across drivers unlike rowcount for multi-row upserts.
        inserted = len(session.execute(stmt).fetchall())

    # Recompute aggregates from what's actually stored (over all chains).
    total, first_seen, last_seen = session.execute(
        select(
            func.count(WalletTransaction.id),
            func.min(WalletTransaction.block_time),
            func.max(WalletTransaction.block_time),
        ).where(WalletTransaction.wallet_id == wallet.id)
    ).one()

    wallet.tx_count = total
    wallet.first_seen = first_seen
    wallet.last_seen = last_seen
    session.commit()

    return LoadResult(wallet_id=wallet.id, inserted=inserted, total=total)
