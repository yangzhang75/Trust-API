"""Shared pytest fixtures.

Tests run against the app factory with a deterministic test Settings
instance so they never depend on the developer's local environment.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from trust_api.config import Settings
from trust_api.db.session import Base, get_db
from trust_api.main import create_app

TEST_API_KEY = "test-key"

_REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def _isolate_provider_key(monkeypatch):
    """Keep tests deterministic regardless of a developer's local .env.

    pydantic-settings loads .env, so a real ETHERSCAN_API_KEY there would make
    Settings() report a configured provider — triggering live ingestion and
    changing behavior/coverage. Force it empty (env vars beat .env); tests that
    want a provider still pass ``etherscan_api_key=...`` explicitly, which wins.
    """
    monkeypatch.setenv("ETHERSCAN_API_KEY", "")


def _test_db_url() -> str:
    """Resolve the test Postgres URL (CI/local override → app default)."""
    return (
        os.environ.get("TEST_DATABASE_URL")
        or os.environ.get("DATABASE_URL")
        or Settings().database_url
    )


def _reset_public_schema(engine: Engine) -> None:
    """Drop and recreate the `public` schema — a true clean slate that also
    removes alembic_version, so a following `alembic upgrade` starts fresh."""
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))


def _alembic_upgrade_head(url: str) -> None:
    """Run `alembic upgrade head` against ``url`` programmatically.

    Sets ALEMBIC_SKIP_LOGGING_CONFIG so migrations/env.py does not run
    fileConfig (which would evict pytest's caplog handler from the root
    logger); restored afterwards so nothing leaks between tests.
    """
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(_REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(_REPO_ROOT / "migrations"))
    cfg.set_main_option("sqlalchemy.url", url)  # honored by migrations/env.py

    prev = os.environ.get("ALEMBIC_SKIP_LOGGING_CONFIG")
    os.environ["ALEMBIC_SKIP_LOGGING_CONFIG"] = "1"
    try:
        command.upgrade(cfg, "head")
    finally:
        if prev is None:
            os.environ.pop("ALEMBIC_SKIP_LOGGING_CONFIG", None)
        else:
            os.environ["ALEMBIC_SKIP_LOGGING_CONFIG"] = prev


def _use_migrations() -> bool:
    """When set, DB fixtures build the schema via migrations, not create_all."""
    return os.environ.get("TEST_USE_MIGRATIONS") == "1"


_PG_HINT = "start Postgres (e.g. `docker start tapi-testpg`, or a postgres:16 container)"
_REDIS_HINT = "start Redis (e.g. `docker start tapi-testredis`, or a redis:7 container)"


def _require_service(ok: bool, name: str, hint: str) -> None:
    """Fail loudly when a required service is missing.

    Silently skipping service-backed tests lets the suite report green while
    the entire integration/chaos layer never ran ("green suite that ran 100
    of 197"). So by default a missing service is a hard failure. Set
    ALLOW_SKIP_TEST_SERVICES=1 to opt into skipping instead (explicit, for
    intentional unit-only local runs).
    """
    if ok:
        return
    if os.environ.get("ALLOW_SKIP_TEST_SERVICES") == "1":
        pytest.skip(f"{name} unavailable (ALLOW_SKIP_TEST_SERVICES=1)")
    pytest.fail(
        f"{name} is required for this test but is not reachable — {hint}. "
        f"To skip service-backed tests explicitly, set ALLOW_SKIP_TEST_SERVICES=1.",
        pytrace=False,
    )


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
    service. By default the schema is built with ``create_all`` (fast); when
    ``TEST_USE_MIGRATIONS=1`` it is built by running the Alembic migrations,
    so the whole suite can be exercised against the migrated schema in CI.
    A missing Postgres is a hard failure (see ``_require_service``).
    """
    url = _test_db_url()
    engine = create_engine(url)
    try:
        engine.connect().close()
    except OperationalError:
        engine.dispose()
        _require_service(False, "Postgres", _PG_HINT)

    if _use_migrations():
        _reset_public_schema(engine)  # clean slate incl. alembic_version
        _alembic_upgrade_head(url)
    else:
        Base.metadata.create_all(engine)
    try:
        yield engine
    finally:
        if _use_migrations():
            _reset_public_schema(engine)
        else:
            Base.metadata.drop_all(engine)
        engine.dispose()


@pytest.fixture
def raw_pg_engine() -> Iterator[Engine]:
    """A bare Postgres engine with NO schema set up — the test manages the
    schema itself (used by the migration tests). Leaves a clean schema behind.
    """
    engine = create_engine(_test_db_url())
    try:
        engine.connect().close()
    except OperationalError:
        engine.dispose()
        _require_service(False, "Postgres", _PG_HINT)
    try:
        yield engine
    finally:
        _reset_public_schema(engine)
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


@pytest.fixture
def metrics_redis() -> Iterator[object]:
    """Reset the shared Redis-backed metrics store.

    CI provides a Redis service. A missing Redis is a hard failure (see
    ``_require_service``) so metrics tests can't be silently skipped.
    """
    import redis as redis_lib

    from trust_api.core.metrics import METRICS

    try:
        METRICS._redis().ping()
    except redis_lib.RedisError:
        _require_service(False, "Redis", _REDIS_HINT)
    METRICS.reset()
    try:
        yield METRICS
    finally:
        METRICS.reset()
