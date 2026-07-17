"""Tests for request usage logging (Week 8)."""

from __future__ import annotations

import hashlib

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker

from tests.conftest import TEST_API_KEY
from trust_api.api.deps import get_redis
from trust_api.api.usage import hash_api_key, record_usage
from trust_api.config import Settings
from trust_api.db.models import UsageEvent
from trust_api.db.session import get_db

VALID_WALLET = "0x52908400098527886E0F7030069857D2E4169EE7"
AUTH = {"X-API-Key": TEST_API_KEY}
PAYLOAD = {"wallet": VALID_WALLET, "chains": ["ethereum"]}
EXPECTED_HASH = hashlib.sha256(TEST_API_KEY.encode("utf-8")).hexdigest()[:16]


class FakeRedis:
    """In-memory stand-in for the rate limiter (incr/expire only)."""

    def __init__(self) -> None:
        self.store: dict[str, int] = {}

    def incr(self, key: str) -> int:
        self.store[key] = self.store.get(key, 0) + 1
        return self.store[key]

    def expire(self, key: str, ttl: int) -> bool:
        return True


def _client(db_engine: Engine, *, limit: int = 1000) -> TestClient:
    from trust_api.main import create_app

    app = create_app(
        Settings(api_keys=TEST_API_KEY, rate_limit_per_minute=limit, environment="test")
    )
    app.state.session_factory = sessionmaker(bind=db_engine)  # write usage to the test DB
    app.dependency_overrides[get_db] = lambda: None  # /verify doesn't need its own DB here
    fake = FakeRedis()  # one shared counter for the client's lifetime
    app.dependency_overrides[get_redis] = lambda: fake
    return TestClient(app)


def _rows(db_engine: Engine) -> list[UsageEvent]:
    with sessionmaker(bind=db_engine)() as s:
        return s.execute(select(UsageEvent)).scalars().all()


# --- hash helper ----------------------------------------------------------


def test_hash_api_key_only_hashes_allowlisted_keys() -> None:
    settings = Settings(api_keys="good-key")
    assert hash_api_key("good-key", settings) == hashlib.sha256(b"good-key").hexdigest()[:16]
    assert hash_api_key("not-a-key", settings) is None
    assert hash_api_key(None, settings) is None


# --- middleware records rows ----------------------------------------------


def test_usage_logged_for_verify(db_engine: Engine) -> None:
    client = _client(db_engine)
    resp = client.post("/verify", json=PAYLOAD, headers=AUTH)
    assert resp.status_code == 200

    rows = _rows(db_engine)
    assert len(rows) == 1
    r = rows[0]
    assert r.endpoint == "/verify"
    assert r.method == "POST"
    assert r.status_code == 200
    assert r.api_key_hash == EXPECTED_HASH  # hashed, never the raw key
    assert r.response_duration_ms is not None and r.response_duration_ms >= 0


def test_usage_records_401_400_and_429(db_engine: Engine) -> None:
    ok = _client(db_engine, limit=1000)
    ok.post("/verify", json={"wallet": "0xnothex", "chains": ["ethereum"]}, headers=AUTH)  # 400
    ok.post("/verify", json=PAYLOAD)  # 401 (no key)

    rl = _client(db_engine, limit=1)
    assert rl.post("/verify", json=PAYLOAD, headers=AUTH).status_code == 200
    assert rl.post("/verify", json=PAYLOAD, headers=AUTH).status_code == 429  # over limit

    by_status = {r.status_code: r for r in _rows(db_engine)}
    assert {400, 401, 429}.issubset(by_status)
    assert by_status[401].api_key_hash is None  # no valid key recorded
    assert by_status[429].api_key_hash == EXPECTED_HASH


def test_usage_write_failure_does_not_break_request(db_engine: Engine) -> None:
    class _BoomSession:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def add(self, *a):
            pass

        def commit(self):
            raise SQLAlchemyError("db down")

    client = _client(db_engine)
    client.app.state.session_factory = lambda: _BoomSession()
    resp = client.post("/verify", json=PAYLOAD, headers=AUTH)
    assert resp.status_code == 200  # failed usage write must not fail the request
    assert _rows(db_engine) == []  # nothing written


def test_record_usage_swallows_db_errors(db_engine: Engine) -> None:
    # Direct unit: a failing factory is logged, not raised.
    def boom_factory():
        raise SQLAlchemyError("cannot connect")

    record_usage(
        boom_factory,
        endpoint="/verify",
        method="POST",
        status_code=200,
        api_key_hash=None,
        duration_ms=1.0,
    )  # must not raise
