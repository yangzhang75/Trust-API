"""Tests for POST /verify/batch — validation, auth, and response shape.

Graph-feature behavior (non-null features, accuracy) is covered separately in
test_verify_batch_graph.py once the graph path is wired in."""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.conftest import TEST_API_KEY
from trust_api.api.deps import get_redis
from trust_api.config import Settings
from trust_api.db.session import get_db
from trust_api.main import create_app

VALID = "0x52908400098527886E0F7030069857D2E4169EE7"
VALID2 = "0xde0B295669a9FD93d5F28D9Ec85E40f4cb697BAe"
AUTH = {"X-API-Key": TEST_API_KEY}


def _client(db=None) -> TestClient:
    app = create_app(
        Settings(api_keys=TEST_API_KEY, rate_limit_per_minute=1000, environment="test")
    )
    app.dependency_overrides[get_db] = lambda: db
    return TestClient(app)


def test_batch_scores_all_wallets_in_input_order() -> None:
    client = _client()
    resp = client.post("/verify/batch", json={"wallets": [VALID, VALID2]}, headers=AUTH)
    assert resp.status_code == 200
    body = resp.json()
    assert [r["wallet"] for r in body] == [VALID, VALID2]  # order preserved
    for r in body:
        assert set(r) >= {"wallet", "human_likelihood", "trust_tier", "risk_flags", "proof"}
        assert r["proof"]["signature"]  # each wallet gets a signed proof


def test_batch_defaults_to_ethereum_chain() -> None:
    client = _client()
    body = client.post("/verify/batch", json={"wallets": [VALID]}, headers=AUTH).json()
    assert body[0]["chains"] == ["ethereum"]


def test_batch_respects_requested_chains() -> None:
    client = _client()
    body = client.post(
        "/verify/batch", json={"wallets": [VALID], "chains": ["ethereum", "arbitrum"]}, headers=AUTH
    ).json()
    assert body[0]["chains"] == ["ethereum", "arbitrum"]


def test_batch_rejects_too_many_wallets() -> None:
    client = _client()
    resp = client.post("/verify/batch", json={"wallets": [VALID] * 101}, headers=AUTH)
    assert resp.status_code == 400
    assert "max 100" in resp.json()["detail"] and "Split" in resp.json()["detail"]


def test_batch_rejects_invalid_wallet() -> None:
    client = _client()
    resp = client.post("/verify/batch", json={"wallets": [VALID, "0xnothex"]}, headers=AUTH)
    assert resp.status_code == 400
    assert "Invalid wallet" in resp.json()["detail"]


def test_batch_rejects_empty_list() -> None:
    client = _client()
    # min_length=1 -> pydantic 422
    assert client.post("/verify/batch", json={"wallets": []}, headers=AUTH).status_code == 422


def test_batch_requires_api_key() -> None:
    client = _client()
    assert client.post("/verify/batch", json={"wallets": [VALID]}).status_code == 401


class _FakeRedis:
    """Counts incr calls (isolated per test, like tests/test_rate_limit.py)."""

    def __init__(self) -> None:
        self.store: dict[str, int] = {}

    def incr(self, key: str) -> int:
        self.store[key] = self.store.get(key, 0) + 1
        return self.store[key]

    def expire(self, key: str, ttl: int) -> bool:
        return True


def test_batch_counts_as_single_rate_limited_request() -> None:
    # limit=1/min with an isolated fake Redis: a 5-wallet batch is ONE request
    # (one incr), so the SECOND call is what trips the limit — proving the batch
    # counted as 1, not as 5.
    app = create_app(Settings(api_keys=TEST_API_KEY, rate_limit_per_minute=1, environment="test"))
    fake = _FakeRedis()  # one shared instance so the counter persists across requests
    app.dependency_overrides[get_db] = lambda: None
    app.dependency_overrides[get_redis] = lambda: fake
    client = TestClient(app)
    first = client.post("/verify/batch", json={"wallets": [VALID] * 5}, headers=AUTH)
    second = client.post("/verify/batch", json={"wallets": [VALID]}, headers=AUTH)
    assert first.status_code == 200
    assert second.status_code == 429
