"""Tests for the background ingestion worker's core pass."""

from __future__ import annotations

import httpx
import respx
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from trust_api import worker as worker_mod
from trust_api.config import Settings
from trust_api.db.models import WalletFeature
from trust_api.pipeline import BatchSummary
from trust_api.schemas.verify import Chain
from trust_api.services.ingestion import load_transactions
from trust_api.worker import ingest_single, ingest_wallets, main, refresh_all

BASE = "https://api.etherscan.io/v2/api"
W1 = "0x52908400098527886E0F7030069857D2E4169EE7"
W2 = "0xde709f2102306220921060314715629080e2fb77"
OTHER = "0x000000000000000000000000000000000000dead"


def _settings() -> Settings:
    return Settings(
        etherscan_api_key="test-provider-key",
        etherscan_base_url=BASE,
        ingestion_backoff_seconds=0,
        ingestion_cache_ttl_seconds=0,
    )


def _row_for(address: str) -> dict:
    return {
        "hash": "0x" + "b" * 64,
        "from": address.lower(),
        "to": OTHER,
        "value": "1",
        "timeStamp": "1700000000",
        "blockNumber": "18000000",
        "contractAddress": "",
    }


@respx.mock
async def test_ingest_wallets_success(db_session: Session) -> None:
    def responder(request: httpx.Request) -> httpx.Response:
        addr = request.url.params.get("address", "")
        return httpx.Response(
            200, json={"status": "1", "message": "OK", "result": [_row_for(addr)]}
        )

    respx.get(BASE).mock(side_effect=responder)

    results = await ingest_wallets(db_session, [W1, W2], Chain.ethereum, settings=_settings())
    assert results == {W1: 1, W2: 1}


async def test_ingest_wallets_skips_invalid_address(db_session: Session) -> None:
    # H2: worker ingestion rejects malformed addresses before any provider call
    # (respx not armed — no HTTP request must be made for an invalid address).
    results = await ingest_wallets(
        db_session, ["0xdeadbeef", "not_an_address"], Chain.ethereum, settings=_settings()
    )
    assert results == {"0xdeadbeef": None, "not_an_address": None}


@respx.mock
async def test_ingest_wallets_isolates_failures(db_session: Session) -> None:
    # Provider returns a hard error: each wallet fails but the pass continues.
    respx.get(BASE).mock(
        return_value=httpx.Response(
            200, json={"status": "0", "message": "Invalid API Key", "result": "bad key"}
        )
    )
    results = await ingest_wallets(db_session, [W1, W2], Chain.ethereum, settings=_settings())
    assert results == {W1: None, W2: None}  # recorded as failed, no exception raised


async def test_ingest_wallets_isolates_unexpected_errors(db_session: Session, monkeypatch) -> None:
    async def boom(*args, **kwargs):
        raise RuntimeError("unexpected")

    monkeypatch.setattr(worker_mod, "ingest_wallet", boom)
    results = await ingest_wallets(db_session, [W1, W2], Chain.ethereum, settings=_settings())
    assert results == {W1: None, W2: None}  # broad failure isolated, session rolled back


def _responder(request: httpx.Request) -> httpx.Response:
    addr = request.url.params.get("address", "")
    return httpx.Response(200, json={"status": "1", "message": "OK", "result": [_row_for(addr)]})


def test_refresh_all_no_wallets(db_engine: Engine, monkeypatch) -> None:
    monkeypatch.setattr(worker_mod, "get_sessionmaker", lambda: sessionmaker(bind=db_engine))
    assert refresh_all() == {}  # empty DB -> nothing to do


def test_refresh_all_ingests_known_wallets(db_engine: Engine, monkeypatch) -> None:
    factory = sessionmaker(bind=db_engine)
    with factory() as s:
        load_transactions(s, W1, Chain.ethereum, [])  # register a wallet
    monkeypatch.setattr(worker_mod, "get_sessionmaker", lambda: factory)
    monkeypatch.setattr("trust_api.services.ingestion.service.get_settings", lambda: _settings())
    with respx.mock:
        respx.get(BASE).mock(side_effect=_responder)
        results = refresh_all()
    assert results == {W1: 1}
    # features are refreshed as part of the same pass
    with factory() as s:
        assert s.execute(select(WalletFeature)).scalars().all()


def test_ingest_single(db_engine: Engine, monkeypatch) -> None:
    factory = sessionmaker(bind=db_engine)
    monkeypatch.setattr(worker_mod, "get_sessionmaker", lambda: factory)
    monkeypatch.setattr("trust_api.services.ingestion.service.get_settings", lambda: _settings())
    with respx.mock:
        respx.get(BASE).mock(side_effect=_responder)
        ingest_single(W1)  # should not raise
    with factory() as s:
        assert s.execute(select(WalletFeature)).scalars().all()  # features computed


def test_ingest_single_provider_failure_creates_no_features(db_engine: Engine, monkeypatch) -> None:
    factory = sessionmaker(bind=db_engine)
    monkeypatch.setattr(worker_mod, "get_sessionmaker", lambda: factory)
    monkeypatch.setattr("trust_api.services.ingestion.service.get_settings", lambda: _settings())
    with respx.mock:
        respx.get(BASE).mock(
            return_value=httpx.Response(
                200, json={"status": "0", "message": "Invalid API Key", "result": "bad"}
            )
        )
        ingest_single(W2)  # provider fails -> no wallet row -> feature refresh is a no-op
    with factory() as s:
        assert s.execute(select(WalletFeature)).scalars().all() == []


def test_main_once(monkeypatch) -> None:
    called = {}
    monkeypatch.setattr(worker_mod, "refresh_all", lambda: called.setdefault("once", True) or {})
    main(["--once"])
    assert called["once"] is True


def test_main_wallet(monkeypatch) -> None:
    seen = {}
    monkeypatch.setattr(worker_mod, "ingest_single", lambda addr: seen.setdefault("addr", addr))
    main(["--wallet", W1])
    assert seen["addr"] == W1


def test_main_scheduled_wires_and_triggers_scoring(monkeypatch) -> None:
    # main() must register the SCORING job (scheduled_score), not refresh_all,
    # and starting the scheduler must not block.
    captured: dict = {}

    class _FakeScheduler:
        def add_job(self, func, *a, **k) -> None:
            captured["func"] = func

        def start(self) -> None:  # returns instead of blocking
            captured["started"] = True

    monkeypatch.setattr("apscheduler.schedulers.blocking.BlockingScheduler", _FakeScheduler)
    main([])
    assert captured["func"] is worker_mod.scheduled_score  # correct job wired
    assert captured["started"] is True

    # Firing the registered job must actually run the scoring pipeline over
    # the stale wallets (this is what the old test never verified).
    calls: dict = {}

    class _Ctx:
        def __enter__(self):
            return object()

        def __exit__(self, *a) -> bool:
            return False

    monkeypatch.setattr(worker_mod, "get_sessionmaker", lambda: (lambda: _Ctx()))
    monkeypatch.setattr("trust_api.pipeline.stale_wallet_addresses", lambda *a, **k: [W1])

    def _spy_score_wallets(session, addresses, settings, **k):
        calls["addresses"] = addresses
        return BatchSummary(
            total=len(addresses), ok=len(addresses), failed=0, duration_ms=0.0, outcomes=[]
        )

    monkeypatch.setattr("trust_api.pipeline.score_wallets", _spy_score_wallets)
    captured["func"]()  # invoke scheduled_score
    assert calls["addresses"] == [W1]  # score_wallets was invoked with the stale wallet
