"""ETL tests: transform normalization (pure) and idempotent load (DB)."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from trust_api.db.models import Wallet, WalletTransaction
from trust_api.schemas.verify import Chain
from trust_api.services.ingestion.load import load_transactions
from trust_api.services.ingestion.models import Transaction
from trust_api.services.ingestion.transform import normalize_transactions

WALLET = "0x52908400098527886E0F7030069857D2E4169EE7"
OTHER = "0x000000000000000000000000000000000000dEaD"


def _row(**kw) -> dict:
    base = {
        "hash": "0x" + "a" * 64,
        "from": WALLET.lower(),
        "to": OTHER.lower(),
        "value": "1000000000000000000",
        "timeStamp": "1700000000",
        "blockNumber": "18000000",
        "contractAddress": "",
    }
    base.update(kw)
    return base


# --- transform (pure, no DB) ---


def test_transform_classifies_out() -> None:
    [tx] = normalize_transactions([_row()], WALLET, Chain.ethereum)
    assert tx.direction == "out"
    assert tx.counterparty == OTHER.lower()
    assert tx.value_wei == 1000000000000000000
    assert tx.block_time == datetime.fromtimestamp(1700000000, tz=UTC)


def test_transform_classifies_in_and_self() -> None:
    [incoming] = normalize_transactions(
        [_row(**{"from": OTHER.lower(), "to": WALLET.lower()})], WALLET, Chain.ethereum
    )
    assert incoming.direction == "in"
    assert incoming.counterparty == OTHER.lower()

    [selftx] = normalize_transactions(
        [_row(**{"from": WALLET.lower(), "to": WALLET.lower()})], WALLET, Chain.ethereum
    )
    assert selftx.direction == "self"


def test_transform_contract_creation_uses_contract_address() -> None:
    [tx] = normalize_transactions(
        [_row(to="", contractAddress="0xC0nTrAcT")], WALLET, Chain.ethereum
    )
    assert tx.direction == "out"
    assert tx.counterparty == "0xc0ntract"


def test_transform_skips_malformed_and_unrelated_rows() -> None:
    rows = [
        _row(value="not-an-int"),  # malformed
        _row(**{"from": OTHER.lower(), "to": OTHER.lower()}),  # unrelated to wallet
        _row(),  # valid
    ]
    assert len(normalize_transactions(rows, WALLET, Chain.ethereum)) == 1


# --- load (idempotent, needs Postgres) ---


def _txs(n: int) -> list[Transaction]:
    return [
        Transaction(
            chain=Chain.ethereum,
            tx_hash=f"0x{i:064x}",
            block_number=18_000_000 + i,
            block_time=datetime.fromtimestamp(1_700_000_000 + i * 60, tz=UTC),
            value_wei=i * 10**18,
            direction="out",
            counterparty=OTHER.lower(),
        )
        for i in range(n)
    ]


def test_load_persists_and_sets_aggregates(db_session: Session) -> None:
    txs = _txs(3)
    result = load_transactions(db_session, WALLET, Chain.ethereum, txs)

    assert result.inserted == 3
    assert result.total == 3

    wallet = db_session.get(Wallet, result.wallet_id)
    assert wallet is not None
    assert wallet.address == WALLET
    assert wallet.tx_count == 3
    assert wallet.first_seen == txs[0].block_time
    assert wallet.last_seen == txs[-1].block_time


def test_load_is_idempotent(db_session: Session) -> None:
    txs = _txs(3)
    first = load_transactions(db_session, WALLET, Chain.ethereum, txs)
    second = load_transactions(db_session, WALLET, Chain.ethereum, txs)

    assert first.inserted == 3
    assert second.inserted == 0  # re-run inserts nothing
    assert second.total == 3

    count = db_session.execute(
        select(func.count(WalletTransaction.id)).where(
            WalletTransaction.wallet_id == first.wallet_id
        )
    ).scalar_one()
    assert count == 3  # no duplicates
    assert first.wallet_id == second.wallet_id  # wallet row reused


def test_load_adds_only_new_transactions_on_partial_overlap(db_session: Session) -> None:
    load_transactions(db_session, WALLET, Chain.ethereum, _txs(2))
    result = load_transactions(db_session, WALLET, Chain.ethereum, _txs(4))
    assert result.inserted == 2  # only the 2 new ones
    assert result.total == 4
