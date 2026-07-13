"""Tests for the end-to-end scoring pipeline."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta

import httpx
import respx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from trust_api import pipeline
from trust_api.config import Settings
from trust_api.db.models import TrustScoreHistory, Wallet, WalletFeature
from trust_api.schemas.verify import HumanLikelihood, TrustTier
from trust_api.services.scoring import ScoringResult

BASE = "https://api.etherscan.io/v2/api"
W1 = "0x52908400098527886E0F7030069857D2E4169EE7"
W2 = "0xde709f2102306220921060314715629080e2fb77"
NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _settings() -> Settings:
    return Settings(
        etherscan_api_key="k",
        etherscan_base_url=BASE,
        ingestion_backoff_seconds=0,
        ingestion_cache_ttl_seconds=0,
    )


def _tx(address: str) -> dict:
    return {
        "hash": "0x" + address[2:10].rjust(64, "0"),
        "from": address.lower(),
        "to": "0x000000000000000000000000000000000000dead",
        "value": "1",
        "timeStamp": "1700000000",
        "blockNumber": "18000000",
        "contractAddress": "",
    }


def _ok_response(request: httpx.Request) -> httpx.Response:
    addr = request.url.params.get("address", "")
    return httpx.Response(200, json={"status": "1", "message": "OK", "result": [_tx(addr)]})


@respx.mock
def test_score_wallet_happy_writes_history(db_session: Session) -> None:
    respx.get(BASE).mock(side_effect=_ok_response)
    outcome = pipeline.score_wallet(db_session, W1, _settings(), now=NOW)
    assert outcome.status == "ok"
    assert outcome.stage is None
    assert outcome.result is not None
    assert outcome.duration_ms >= 0
    rows = db_session.execute(select(TrustScoreHistory)).scalars().all()
    assert len(rows) == 1
    assert rows[0].scorer_version == pipeline.SCORER_VERSION


def test_score_wallet_rejects_invalid_address(db_session: Session) -> None:
    # H2: a malformed address fails at the validate stage, before any provider
    # call — no ingest, no persisted score. (respx not armed: no HTTP expected.)
    outcome = pipeline.score_wallet(db_session, "0xdeadbeef", _settings(), now=NOW)
    assert outcome.status == "error"
    assert outcome.stage == "validate"
    assert outcome.error_type == "InvalidWalletError"
    rows = db_session.execute(select(func.count(TrustScoreHistory.id))).scalar_one()
    assert rows == 0  # nothing persisted for the invalid address


@respx.mock
def test_batch_rejects_invalid_address_but_scores_valid(db_session: Session) -> None:
    # H2 at the batch entry point: bad rejected at validate, good still scored.
    respx.get(BASE).mock(side_effect=_ok_response)
    summary = pipeline.score_wallets(db_session, ["not_an_address", W1], _settings(), now=NOW)
    assert summary.total == 2
    assert summary.ok == 1
    assert summary.failed == 1
    by_addr = {o.address: o for o in summary.outcomes}
    assert by_addr["not_an_address"].stage == "validate"
    assert by_addr[W1].status == "ok"


@respx.mock
def test_batch_isolates_a_failing_wallet(db_session: Session) -> None:
    def responder(request: httpx.Request) -> httpx.Response:
        addr = request.url.params.get("address", "").lower()
        if addr == W2.lower():  # W2 fails at ingest
            return httpx.Response(
                200, json={"status": "0", "message": "Invalid API Key", "result": "bad"}
            )
        return _ok_response(request)

    respx.get(BASE).mock(side_effect=responder)
    summary = pipeline.score_wallets(db_session, [W1, W2], _settings(), now=NOW)
    assert summary.total == 2
    assert summary.ok == 1
    assert summary.failed == 1
    by_addr = {o.address: o for o in summary.outcomes}
    assert by_addr[W1].status == "ok"
    assert by_addr[W2].status == "error"
    assert by_addr[W2].stage == "ingest"
    assert by_addr[W2].error_type  # populated


@respx.mock
def test_feature_stage_failure_is_isolated(db_session: Session, monkeypatch) -> None:
    respx.get(BASE).mock(side_effect=_ok_response)

    def boom(*a, **k):
        raise RuntimeError("feature boom")

    monkeypatch.setattr(pipeline, "compute_features", boom)
    outcome = pipeline.score_wallet(db_session, W1, _settings(), now=NOW)
    assert outcome.status == "error"
    assert outcome.stage == "feature"


@respx.mock
def test_score_stage_failure_is_isolated(db_session: Session, monkeypatch) -> None:
    respx.get(BASE).mock(side_effect=_ok_response)
    monkeypatch.setattr(pipeline, "score", lambda *_a, **_k: (_ for _ in ()).throw(ValueError("x")))
    outcome = pipeline.score_wallet(db_session, W1, _settings(), now=NOW)
    assert outcome.status == "error"
    assert outcome.stage == "score"


@respx.mock
def test_persist_stage_failure_is_isolated(db_session: Session, monkeypatch) -> None:
    respx.get(BASE).mock(side_effect=_ok_response)

    def boom(*a, **k):
        raise RuntimeError("persist boom")

    monkeypatch.setattr(pipeline, "_persist", boom)
    outcome = pipeline.score_wallet(db_session, W1, _settings(), now=NOW)
    assert outcome.status == "error"
    assert outcome.stage == "persist"


def _events(caplog) -> list[dict]:
    return [
        json.loads(r.getMessage())
        for r in caplog.records
        if r.name == "trust_api.pipeline" and r.getMessage().startswith("{")
    ]


@respx.mock
def test_pipeline_emits_structured_stage_logs(db_session: Session, caplog) -> None:
    caplog.set_level(logging.INFO, logger="trust_api.pipeline")
    respx.get(BASE).mock(side_effect=_ok_response)
    pipeline.score_wallet(db_session, W1, _settings(), now=NOW)
    stages = [e for e in _events(caplog) if e.get("stage")]
    assert {e["stage"] for e in stages} == {"validate", "ingest", "feature", "score", "persist"}
    assert all(e["status"] == "ok" for e in stages)
    assert all(e["wallet"] == W1 and e["scorer_version"] and "duration_ms" in e for e in stages)


@respx.mock
def test_pipeline_logs_stage_error_and_batch_summary(
    db_session: Session, caplog, monkeypatch
) -> None:
    caplog.set_level(logging.INFO, logger="trust_api.pipeline")
    respx.get(BASE).mock(side_effect=_ok_response)
    monkeypatch.setattr(pipeline, "score", lambda *_a, **_k: (_ for _ in ()).throw(ValueError("x")))
    pipeline.score_wallets(db_session, [W1], _settings(), now=NOW)
    events = _events(caplog)
    err = [e for e in events if e.get("stage") == "score"]
    assert err and err[0]["status"] == "error" and err[0]["error_type"] == "ValueError"
    summary = [e for e in events if e.get("event") == "batch_summary"]
    assert summary and summary[0]["total"] == 1 and summary[0]["failed"] == 1


def _wallet(session: Session, address: str) -> int:
    w = Wallet(address=address)
    session.add(w)
    session.flush()
    session.add(WalletFeature(wallet_id=w.id, chain="ethereum", payload={}))
    session.commit()
    return w.id


def test_persist_is_append_only_per_scorer_version(db_session: Session, monkeypatch) -> None:
    wid = _wallet(db_session, W1)
    result = ScoringResult(HumanLikelihood.low, TrustTier.bronze, 0.1, [])

    pipeline._persist(db_session, wid, result, NOW)
    pipeline._persist(db_session, wid, result, NOW)  # same version -> upsert, no dup
    count = db_session.execute(select(func.count(TrustScoreHistory.id))).scalar_one()
    assert count == 1

    monkeypatch.setattr(pipeline, "SCORER_VERSION", "9.9.9-test")  # version bump -> new row
    pipeline._persist(db_session, wid, result, NOW)
    count = db_session.execute(select(func.count(TrustScoreHistory.id))).scalar_one()
    assert count == 2


def test_known_and_stale_wallet_helpers(db_session: Session) -> None:
    fresh = _wallet(db_session, W1)
    stale_wid = _wallet(db_session, W2)
    # fresh wallet has a recent score at the current version
    db_session.add(
        TrustScoreHistory(
            wallet_id=fresh,
            human_likelihood="high",
            trust_tier="gold",
            confidence_score=0.9,
            risk_flags=[],
            scorer_version=pipeline.SCORER_VERSION,
            scored_at=NOW,
        )
    )
    db_session.commit()

    assert set(pipeline.known_wallet_addresses(db_session)) == {W1, W2}
    stale = pipeline.stale_wallet_addresses(db_session, hours=24, now=NOW + timedelta(hours=1))
    assert stale == [W2]  # only the never-scored wallet is stale
    assert stale_wid  # (referenced)
