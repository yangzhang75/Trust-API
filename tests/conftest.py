"""Shared pytest fixtures.

Tests run against the app factory with a deterministic test Settings
instance so they never depend on the developer's local environment.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from trust_api.config import Settings
from trust_api.db.session import Base, get_db
from trust_api.main import create_app

TEST_API_KEY = "test-key"


@pytest.fixture
def settings() -> Settings:
    """Settings with a known API key and rate limit for tests."""
    return Settings(
        api_keys=TEST_API_KEY,
        rate_limit_per_minute=1000,
        environment="test",
    )


@pytest.fixture
def client(settings: Settings) -> TestClient:
    """A TestClient bound to an app built from the test settings.

    /verify's DB read is disabled (get_db -> None) so these tests never
    depend on a database; DB-backed /verify behavior is covered separately.
    """
    app = create_app(settings)
    app.dependency_overrides[get_db] = lambda: None
    return TestClient(app)


@pytest.fixture
def db_engine() -> Iterator[Engine]:
    """A SQLAlchemy engine against a real Postgres test database.

    Uses TEST_DATABASE_URL (or DATABASE_URL) — CI provides a Postgres
    service. Skips cleanly when no database is reachable so contributors
    without a local Postgres aren't blocked.
    """
    url = (
        os.environ.get("TEST_DATABASE_URL")
        or os.environ.get("DATABASE_URL")
        or Settings().database_url
    )
    engine = create_engine(url)
    try:
        engine.connect().close()
    except OperationalError:
        engine.dispose()
        pytest.skip("no Postgres available for DB tests")

    Base.metadata.create_all(engine)
    try:
        yield engine
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


@pytest.fixture
def db_session(db_engine: Engine) -> Iterator[Session]:
    """A SQLAlchemy session bound to the test engine."""
    session = sessionmaker(bind=db_engine)()
    try:
        yield session
    finally:
        session.rollback()
        session.close()
