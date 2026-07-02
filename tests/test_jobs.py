"""Tests for the compute_features batch job (CLI + run())."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from trust_api.db.models import Wallet, WalletFeature, WalletTransaction
from trust_api.jobs import compute_features as job

CP = "0x000000000000000000000000000000000000aaaa"


def _wallet_with_tx(session: Session, address: str) -> int:
    w = Wallet(address=address)
    session.add(w)
    session.flush()
    session.add(
        WalletTransaction(
            wallet_id=w.id,
            chain="ethereum",
            tx_hash=f"0x{w.id:064x}",
            block_number=1,
            block_time=datetime(2025, 12, 30, tzinfo=UTC),
            value_wei=1,
            direction="out",
            counterparty=CP,
        )
    )
    return w.id


def test_run_no_wallets_returns_empty(db_session: Session) -> None:
    assert job.run(db_session) == {}


def test_run_all_wallets_with_transactions(db_session: Session) -> None:
    wid = _wallet_with_tx(db_session, "0x" + "a" * 40)
    db_session.commit()
    results = job.run(db_session)  # default = all with txs
    assert results == {wid: True}
    row = db_session.execute(
        select(WalletFeature).where(WalletFeature.wallet_id == wid)
    ).scalar_one()
    assert row.tx_count == 1


def test_run_specific_wallet_ids(db_session: Session) -> None:
    a = _wallet_with_tx(db_session, "0x" + "a" * 40)
    _wallet_with_tx(db_session, "0x" + "b" * 40)
    db_session.commit()
    results = job.run(db_session, wallet_ids=[a])  # only 'a'
    assert results == {a: True}


def test_main_computes_features(db_engine, monkeypatch) -> None:
    factory = sessionmaker(bind=db_engine)
    with factory() as s:
        _wallet_with_tx(s, "0x" + "c" * 40)
        s.commit()
    monkeypatch.setattr(job, "get_sessionmaker", lambda: factory)
    job.main([])  # should run without error over all wallets
    with factory() as s:
        assert s.execute(select(WalletFeature)).scalars().all()  # a feature row exists
