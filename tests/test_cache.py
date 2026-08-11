"""Tests for the /verify assessment cache (core.cache) + the X-Cache header."""

from __future__ import annotations

import redis as redis_lib
from fastapi.testclient import TestClient

from tests.conftest import TEST_API_KEY
from trust_api.api.deps import get_redis
from trust_api.config import Settings
from trust_api.core.cache import AssessmentCache
from trust_api.db.session import get_db
from trust_api.main import create_app
from trust_api.schemas.verify import HumanLikelihood, RiskFlag, TrustTier
from trust_api.services.scoring import ScoringResult

WALLET = "0x52908400098527886E0F7030069857D2E4169EE7"
AUTH = {"X-API-Key": TEST_API_KEY}
RESULT = ScoringResult(HumanLikelihood.high, TrustTier.gold, 0.8375, [RiskFlag.dormant])


class FakeRedis:
    """In-memory stand-in supporting the cache (get/set) + limiter (incr/expire)."""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    def get(self, key: str):
        return self.store.get(key)

    def set(self, key: str, value: str, ex: int | None = None) -> bool:
        self.store[key] = value
        return True

    def incr(self, key: str) -> int:
        self.store[key] = str(int(self.store.get(key, "0")) + 1)
        return int(self.store[key])

    def expire(self, key: str, ttl: int) -> bool:
        return True


class FailingRedis:
    def get(self, key: str):
        raise redis_lib.RedisError("down")

    def set(self, key: str, value: str, ex: int | None = None):
        raise redis_lib.RedisError("down")

    def incr(self, key: str):  # rate limiter (fails open)
        raise redis_lib.RedisError("down")

    def expire(self, key: str, ttl: int):
        raise redis_lib.RedisError("down")


# --- unit: AssessmentCache ------------------------------------------------


def test_cache_round_trip_hit() -> None:
    cache = AssessmentCache(FakeRedis(), ttl_seconds=30)
    assert cache.get(WALLET, ["ethereum"]) is None  # miss
    cache.set(WALLET, ["ethereum"], RESULT)
    got = cache.get(WALLET, ["ethereum"])
    assert got is not None
    assert (got.human_likelihood, got.trust_tier, got.confidence_score) == (
        RESULT.human_likelihood,
        RESULT.trust_tier,
        RESULT.confidence_score,
    )
    assert got.risk_flags == RESULT.risk_flags


def test_cache_disabled_when_ttl_zero() -> None:
    fake = FakeRedis()
    cache = AssessmentCache(fake, ttl_seconds=0)
    assert cache.enabled is False
    cache.set(WALLET, ["ethereum"], RESULT)
    assert fake.store == {}  # nothing written
    assert cache.get(WALLET, ["ethereum"]) is None  # never reads


def test_cache_degrades_on_redis_error() -> None:
    cache = AssessmentCache(FailingRedis(), ttl_seconds=30)
    cache.set(WALLET, ["ethereum"], RESULT)  # swallowed
    assert cache.get(WALLET, ["ethereum"]) is None  # miss, no raise


def test_cache_key_varies_by_chains() -> None:
    fake = FakeRedis()
    cache = AssessmentCache(fake, ttl_seconds=30)
    cache.set(WALLET, ["ethereum"], RESULT)
    assert cache.get(WALLET, ["ethereum", "arbitrum"]) is None  # different key


# --- endpoint: X-Cache header --------------------------------------------


def _client(redis_obj, db=None) -> TestClient:
    app = create_app(
        Settings(api_keys=TEST_API_KEY, rate_limit_per_minute=1000, environment="test")
    )
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_redis] = lambda: redis_obj
    return TestClient(app)


def test_verify_sets_x_cache_miss_then_hit() -> None:
    client = _client(FakeRedis())
    first = client.post("/verify", json={"wallet": WALLET}, headers=AUTH)
    second = client.post("/verify", json={"wallet": WALLET}, headers=AUTH)
    assert first.headers["X-Cache"] == "MISS"
    assert second.headers["X-Cache"] == "HIT"
    # cache hit returns the same assessment but a FRESH proof (unique nonce)
    assert first.json()["trust_tier"] == second.json()["trust_tier"]
    assert first.json()["proof"]["nonce"] != second.json()["proof"]["nonce"]


def test_verify_cache_miss_on_redis_outage() -> None:
    client = _client(FailingRedis())
    resp = client.post("/verify", json={"wallet": WALLET}, headers=AUTH)
    assert resp.status_code == 200
    assert resp.headers["X-Cache"] == "MISS"  # degrades gracefully
