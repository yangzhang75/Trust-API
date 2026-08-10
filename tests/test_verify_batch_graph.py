"""Graph-feature wiring for the batch path (pipeline + endpoint).

Seeds a real cluster (A/B/C share a funder + counterparty) plus an isolated
wallet, then verifies score_batch_with_graph / POST /verify/batch populate the
graph (cluster) features that single-wallet /verify leaves NULL."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

import trust_api.pipeline as pipeline
from tests.conftest import TEST_API_KEY
from trust_api.config import Settings
from trust_api.db.models import TrustScoreHistory, Wallet, WalletFeature, WalletTransaction
from trust_api.db.session import get_db
from trust_api.main import create_app
from trust_api.pipeline import _ensure_ingested, _get_or_create_wallet_id, score_batch_with_graph
from trust_api.services.ingestion import IngestionError

A = "0x" + "a" * 40
B = "0x" + "b" * 40
C = "0x" + "c" * 40
Z = "0x" + "d" * 40  # isolated
E = "0x" + "e" * 40  # never seeded -> exercises get-or-create's "create" branch
F = "0x" + "f" * 40  # shared external funder
X = "0x" + "9" * 40  # shared counterparty
AUTH = {"X-API-Key": TEST_API_KEY}


def _wallet(session: Session, address: str) -> int:
    w = Wallet(address=address)
    session.add(w)
    session.flush()
    return w.id


def _tx(session: Session, wid: int, i: int, direction: str, cp: str) -> None:
    session.add(
        WalletTransaction(
            wallet_id=wid,
            chain="ethereum",
            tx_hash=f"0x{wid:032x}{i:032x}",
            block_number=1000 + i,
            block_time=datetime(2025, 1, 1, tzinfo=UTC),
            value_wei=1,
            direction=direction,
            counterparty=cp,
        )
    )


def _seed_cluster(session: Session) -> None:
    a, b, c, z = (_wallet(session, addr) for addr in (A, B, C, Z))
    _tx(session, a, 1, "in", F)
    _tx(session, a, 2, "out", X)
    _tx(session, b, 1, "in", A)
    _tx(session, b, 2, "in", F)
    _tx(session, b, 3, "out", X)
    _tx(session, c, 1, "in", B)
    _tx(session, c, 2, "in", F)
    _tx(session, c, 3, "out", X)
    _tx(session, z, 1, "in", "0x" + "1" * 40)
    _tx(session, z, 2, "out", "0x" + "2" * 40)
    session.commit()


def test_score_batch_with_graph_populates_cluster_features(db_session: Session) -> None:
    _seed_cluster(db_session)
    settings = Settings(environment="test")  # no provider -> uses seeded data

    scored = score_batch_with_graph(db_session, [A, B, C, Z, E], settings)

    # Results in input order, one per wallet (E was created on the fly).
    assert [s.address for s in scored] == [A, B, C, Z, E]
    ctx = {s.address: s.graph_context_size for s in scored}
    assert ctx[A] == ctx[B] == ctx[C] == 3  # connected component of 3
    assert ctx[Z] == 1 and ctx[E] == 1  # isolated

    # The graph feature columns are now NON-NULL for the cluster (the Week-10
    # gap was these being NULL under single-wallet /verify).
    feat_a = db_session.execute(
        select(WalletFeature).join(Wallet).where(Wallet.address == A)
    ).scalar_one()
    assert feat_a.shared_funder_score and feat_a.shared_funder_score > 0
    assert feat_a.cluster_size_estimate == 3

    # History persisted for every wallet.
    assert db_session.execute(select(TrustScoreHistory)).scalars().all()


def test_ensure_ingested_uses_provider_when_configured(db_session, monkeypatch) -> None:
    existing = _get_or_create_wallet_id(db_session, A)

    async def fake_ingest(session, address, settings):
        return existing

    monkeypatch.setattr(pipeline, "_ingest", fake_ingest)
    settings = Settings(environment="test", etherscan_api_key="k")
    assert _ensure_ingested(db_session, A, settings) == existing


def test_ensure_ingested_falls_back_on_ingestion_error(db_session, monkeypatch) -> None:
    async def boom(session, address, settings):
        raise IngestionError("provider down")

    monkeypatch.setattr(pipeline, "_ingest", boom)
    settings = Settings(environment="test", etherscan_api_key="k")
    wid = _ensure_ingested(db_session, E, settings)  # falls back to get-or-create
    assert isinstance(wid, int) and wid > 0


def test_batch_endpoint_populates_graph_features(db_session: Session) -> None:
    _seed_cluster(db_session)
    app = create_app(
        Settings(api_keys=TEST_API_KEY, rate_limit_per_minute=1000, environment="test")
    )
    app.dependency_overrides[get_db] = lambda: db_session
    resp = TestClient(app).post("/verify/batch", json={"wallets": [A, B, C, Z]}, headers=AUTH)
    assert resp.status_code == 200
    assert [r["wallet"] for r in resp.json()] == [A, B, C, Z]
    feat_a = db_session.execute(
        select(WalletFeature).join(Wallet).where(Wallet.address == A)
    ).scalar_one()
    assert feat_a.cluster_size_estimate == 3  # graph features populated via the endpoint
