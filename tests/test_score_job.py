"""Tests for the scoring job runner and the worker's scheduled scoring pass."""

from __future__ import annotations

import httpx
import respx
from sqlalchemy import func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from trust_api import worker as worker_mod
from trust_api.config import Settings
from trust_api.db.models import TrustScoreHistory, Wallet, WalletFeature
from trust_api.jobs import score as score_job
from trust_api.pipeline import score_wallets

BASE = "https://api.etherscan.io/v2/api"
W1 = "0x52908400098527886E0F7030069857D2E4169EE7"
W2 = "0xde709f2102306220921060314715629080e2fb77"


def _settings() -> Settings:
    return Settings(
        etherscan_api_key="k",
        etherscan_base_url=BASE,
        ingestion_backoff_seconds=0,
        ingestion_cache_ttl_seconds=0,
        worker_stale_hours=24,
    )


def _ok(request: httpx.Request) -> httpx.Response:
    addr = request.url.params.get("address", "")
    raw = {
        "hash": "0x" + addr[2:10].rjust(64, "0"),
        "from": addr.lower(),
        "to": "0x000000000000000000000000000000000000dead",
        "value": "1",
        "timeStamp": "1700000000",
        "blockNumber": "18000000",
        "contractAddress": "",
    }
    return httpx.Response(200, json={"status": "1", "message": "OK", "result": [raw]})


def _register(session: Session, address: str) -> None:
    w = Wallet(address=address)
    session.add(w)
    session.flush()
    session.add(WalletFeature(wallet_id=w.id, chain="ethereum", payload={}))
    session.commit()


# --- resolve_addresses (mode dispatch) ------------------------------------


def test_resolve_wallet_mode() -> None:
    args = score_job._parser().parse_args(["--wallet", W1])
    assert score_job.resolve_addresses(None, args) == [W1]


def test_resolve_batch_mode(tmp_path) -> None:
    f = tmp_path / "addrs.txt"
    f.write_text(f"{W1}\n\n{W2}\n")
    args = score_job._parser().parse_args(["--batch", str(f)])
    assert score_job.resolve_addresses(None, args) == [W1, W2]


def test_resolve_refresh_all_mode(db_session: Session) -> None:
    _register(db_session, W1)
    args = score_job._parser().parse_args(["--refresh-all"])
    assert score_job.resolve_addresses(db_session, args) == [W1]


def test_resolve_refresh_stale_mode(db_session: Session) -> None:
    _register(db_session, W1)  # no score row -> stale
    args = score_job._parser().parse_args(["--refresh-stale", "--hours", "12"])
    assert score_job.resolve_addresses(db_session, args) == [W1]


# --- run + main -----------------------------------------------------------


@respx.mock
def test_run_scores_and_persists(db_session: Session) -> None:
    respx.get(BASE).mock(side_effect=_ok)
    summary = score_job.run(db_session, [W1], _settings())
    assert summary.ok == 1
    count = db_session.execute(select(func.count(TrustScoreHistory.id))).scalar_one()
    assert count == 1


def test_main_refresh_all_empty_db(db_engine: Engine, monkeypatch) -> None:
    monkeypatch.setattr(score_job, "get_sessionmaker", lambda: sessionmaker(bind=db_engine))
    score_job.main(["--refresh-all"])  # no wallets -> no error


# --- worker.scheduled_score ----------------------------------------------


def test_scheduled_score_no_stale_wallets(db_engine: Engine, monkeypatch) -> None:
    monkeypatch.setattr(worker_mod, "get_sessionmaker", lambda: sessionmaker(bind=db_engine))
    assert worker_mod.scheduled_score() == {"total": 0, "ok": 0, "failed": 0}


@respx.mock
def test_scheduled_score_scores_stale_wallets(db_engine: Engine, monkeypatch) -> None:
    factory = sessionmaker(bind=db_engine)
    with factory() as s:
        _register(s, W1)  # registered but never scored -> stale
    respx.get(BASE).mock(side_effect=_ok)
    monkeypatch.setattr(worker_mod, "get_sessionmaker", lambda: factory)
    monkeypatch.setattr("trust_api.config.get_settings", lambda: _settings())
    result = worker_mod.scheduled_score()
    assert result["total"] == 1 and result["ok"] == 1
    with factory() as s:
        assert s.execute(select(func.count(TrustScoreHistory.id))).scalar_one() == 1


def test_scheduled_score_uses_score_wallets_symbol() -> None:
    # guard: the pipeline entry point the scheduler relies on exists
    assert callable(score_wallets)
