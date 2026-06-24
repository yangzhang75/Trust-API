"""Tests for the DB schema metadata and lazy session wiring.

These exercise the ORM model definitions and the engine/session factory
without opening a real connection (the engine is created lazily and a
Session does not connect until first use).
"""

from __future__ import annotations

from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from trust_api.db import models
from trust_api.db.session import Base, get_db, get_engine, get_sessionmaker

EXPECTED_TABLES = {
    "wallets",
    "wallet_features",
    "trust_scores",
    "proofs",
    "api_keys",
    "usage_events",
}


def test_all_tables_registered() -> None:
    assert EXPECTED_TABLES <= set(Base.metadata.tables)


def test_models_expose_expected_columns() -> None:
    # api_keys stores a hash, never plaintext.
    cols = {c.name for c in models.ApiKey.__table__.columns}
    assert "key_hash" in cols
    assert "plaintext" not in cols
    # proofs/wallet_features carry jsonb payloads.
    assert "payload" in {c.name for c in models.Proof.__table__.columns}
    assert "payload" in {c.name for c in models.WalletFeature.__table__.columns}


def test_engine_and_sessionmaker_are_lazy_and_cached() -> None:
    engine = get_engine()
    assert isinstance(engine, Engine)
    assert get_engine() is engine  # cached

    maker = get_sessionmaker()
    assert get_sessionmaker() is maker  # cached


def test_get_db_yields_and_closes_session() -> None:
    gen = get_db()
    session = next(gen)
    assert isinstance(session, Session)
    # Exhaust the generator to trigger the finally/close branch.
    for _ in gen:
        pass
