"""Tests for the Week 3 behavioral feature computation."""

from __future__ import annotations

from datetime import UTC, datetime

import httpx
import respx
from sqlalchemy import select
from sqlalchemy.orm import Session

from trust_api.config import Settings
from trust_api.db.models import Wallet, WalletFeature, WalletTransaction
from trust_api.schemas.verify import Chain
from trust_api.services.features import (
    all_wallet_ids_with_transactions,
    compute_features,
    compute_features_for_wallets,
)
from trust_api.services.features import service as feature_service
from trust_api.services.ingestion import ingest_wallet

NOW = datetime(2026, 1, 1, tzinfo=UTC)
CP_A = "0x000000000000000000000000000000000000aaaa"
CP_B = "0x000000000000000000000000000000000000bbbb"


def _wallet(session: Session, address: str = "0x" + "1" * 40) -> int:
    w = Wallet(address=address)
    session.add(w)
    session.flush()
    return w.id


def _add(session: Session, wallet_id: int, i: int, when: datetime, direction: str, cp: str) -> None:
    session.add(
        WalletTransaction(
            wallet_id=wallet_id,
            chain="ethereum",
            tx_hash=f"0x{i:064x}",
            block_number=1000 + i,
            block_time=when,
            value_wei=1,
            direction=direction,
            counterparty=cp,
        )
    )


def test_features_on_normal_wallet(db_session: Session) -> None:
    wid = _wallet(db_session)
    _add(db_session, wid, 1, datetime(2025, 12, 30, 10, 0, tzinfo=UTC), "out", CP_A)
    _add(db_session, wid, 2, datetime(2025, 12, 30, 10, 30, tzinfo=UTC), "in", CP_B)
    _add(db_session, wid, 3, datetime(2025, 12, 31, 11, 0, tzinfo=UTC), "out", CP_A)
    db_session.commit()

    f = compute_features(db_session, wid, now=NOW)
    assert f.tx_count == 3
    assert f.active_days == 2
    assert f.counterparty_count == 2
    assert f.tx_per_active_day == 1.5
    assert f.counterparty_diversity_ratio == round(2 / 3, 6)
    assert f.inbound_ratio == round(1 / 3, 6)
    assert f.burst_score == 2  # two txs share the 10:00 hour
    assert f.wallet_age_days == 1
    assert f.recency_days == 0
    assert f.dormancy_flag is False


def test_features_on_dormant_wallet(db_session: Session) -> None:
    wid = _wallet(db_session)
    _add(db_session, wid, 1, datetime(2025, 9, 1, 0, 0, tzinfo=UTC), "out", CP_A)
    db_session.commit()

    f = compute_features(db_session, wid, now=NOW)
    assert f.recency_days == 122
    assert f.dormancy_flag is True  # inactive > 90 days
    assert f.wallet_age_days == 122
    assert f.inbound_ratio == 0.0


def test_features_on_burst_wallet(db_session: Session) -> None:
    wid = _wallet(db_session)
    for i in range(5):
        _add(db_session, wid, i, datetime(2025, 12, 31, 12, i * 10, tzinfo=UTC), "out", CP_A)
    db_session.commit()

    f = compute_features(db_session, wid, now=NOW)
    assert f.burst_score == 5  # all five in the 12:00 hour
    assert f.active_days == 1
    assert f.tx_per_active_day == 5.0
    assert f.counterparty_diversity_ratio == 0.2


def test_features_on_empty_wallet(db_session: Session) -> None:
    wid = _wallet(db_session)
    db_session.commit()

    f = compute_features(db_session, wid, now=NOW)
    assert f.tx_count == 0
    assert f.active_days == 0
    assert f.tx_per_active_day == 0.0
    assert f.counterparty_diversity_ratio == 0.0
    assert f.inbound_ratio == 0.0
    assert f.burst_score == 0
    assert f.wallet_age_days == 0
    assert f.recency_days == 0
    assert f.dormancy_flag is False


def test_features_are_persisted_and_idempotent(db_session: Session) -> None:
    wid = _wallet(db_session)
    _add(db_session, wid, 1, datetime(2025, 12, 30, 10, 0, tzinfo=UTC), "out", CP_A)
    db_session.commit()

    compute_features(db_session, wid, now=NOW)
    compute_features(db_session, wid, now=NOW)  # second run must upsert, not duplicate

    rows = (
        db_session.execute(select(WalletFeature).where(WalletFeature.wallet_id == wid))
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert rows[0].tx_count == 1
    assert rows[0].chain == Chain.ethereum.value


@respx.mock
async def test_features_from_ingested_data(db_session: Session) -> None:
    # Seed via the ingestion path (mocked provider), then compute features.
    base = "https://api.etherscan.io/v2/api"
    wallet = "0x52908400098527886E0F7030069857D2E4169EE7"
    raw = {
        "hash": "0x" + "e" * 64,
        "from": wallet.lower(),
        "to": CP_A,
        "value": "1",
        "timeStamp": "1735646400",  # 2024-12-31T12:00:00Z
        "blockNumber": "18000000",
        "contractAddress": "",
    }
    respx.get(base).mock(
        return_value=httpx.Response(200, json={"status": "1", "message": "OK", "result": [raw]})
    )
    settings = Settings(
        etherscan_api_key="k",
        etherscan_base_url=base,
        ingestion_backoff_seconds=0,
        ingestion_cache_ttl_seconds=0,
    )
    load = await ingest_wallet(db_session, wallet, Chain.ethereum, settings=settings)

    f = compute_features(db_session, load.wallet_id, now=NOW)
    assert f.tx_count == 1
    assert f.counterparty_count == 1
    assert f.inbound_ratio == 0.0


def test_compute_features_for_wallets_isolates_failures(db_session: Session, monkeypatch) -> None:
    good = _wallet(db_session, "0x" + "a" * 40)
    bad = _wallet(db_session, "0x" + "b" * 40)
    _add(db_session, good, 1, datetime(2025, 12, 30, tzinfo=UTC), "out", CP_A)
    db_session.commit()

    real = feature_service.compute_features

    def flaky(session, wallet_id, *, now=None):
        if wallet_id == bad:
            raise RuntimeError("boom")
        return real(session, wallet_id, now=now)

    monkeypatch.setattr(feature_service, "compute_features", flaky)
    results = compute_features_for_wallets(db_session, [good, bad], now=NOW)
    assert results == {good: True, bad: False}


def test_all_wallet_ids_with_transactions(db_session: Session) -> None:
    with_tx = _wallet(db_session, "0x" + "c" * 40)
    _wallet(db_session, "0x" + "d" * 40)  # no transactions
    _add(db_session, with_tx, 1, datetime(2025, 12, 30, tzinfo=UTC), "out", CP_A)
    db_session.commit()

    assert all_wallet_ids_with_transactions(db_session) == [with_tx]
