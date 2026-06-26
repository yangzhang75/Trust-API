"""Tests for the Redis-backed per-key rate limiter.

A fake Redis is injected via dependency override so these run without a
real Redis and deterministically exercise both the 429 path and the
fail-open-on-outage path.
"""

from __future__ import annotations

import redis as redis_lib
from fastapi.testclient import TestClient

from tests.conftest import TEST_API_KEY
from trust_api.api.deps import get_redis
from trust_api.config import Settings
from trust_api.main import create_app

VALID_WALLET = "0x52908400098527886E0F7030069857D2E4169EE7"
AUTH = {"X-API-Key": TEST_API_KEY}
PAYLOAD = {"wallet": VALID_WALLET, "chains": ["ethereum"]}


class FakeRedis:
    """Minimal Redis stand-in supporting the limiter's incr/expire."""

    def __init__(self) -> None:
        self.store: dict[str, int] = {}

    def incr(self, key: str) -> int:
        self.store[key] = self.store.get(key, 0) + 1
        return self.store[key]

    def expire(self, key: str, ttl: int) -> bool:
        return True


class FailingRedis:
    """Redis stand-in that simulates an outage."""

    def incr(self, key: str) -> int:
        raise redis_lib.RedisError("redis is down")

    def expire(self, key: str, ttl: int) -> bool:
        raise redis_lib.RedisError("redis is down")


def _client(limit: int, fake: object) -> TestClient:
    app = create_app(
        Settings(api_keys=TEST_API_KEY, rate_limit_per_minute=limit, environment="test")
    )
    app.dependency_overrides[get_redis] = lambda: fake
    return TestClient(app)


def test_rate_limit_exceeded_returns_429() -> None:
    client = _client(limit=2, fake=FakeRedis())
    assert client.post("/verify", json=PAYLOAD, headers=AUTH).status_code == 200
    assert client.post("/verify", json=PAYLOAD, headers=AUTH).status_code == 200
    resp = client.post("/verify", json=PAYLOAD, headers=AUTH)
    assert resp.status_code == 429
    assert resp.headers.get("Retry-After") == "60"


def test_rate_limit_fails_open_when_redis_unavailable() -> None:
    # limit=1 but Redis is down -> requests are allowed (fail open).
    client = _client(limit=1, fake=FailingRedis())
    assert client.post("/verify", json=PAYLOAD, headers=AUTH).status_code == 200
    assert client.post("/verify", json=PAYLOAD, headers=AUTH).status_code == 200
