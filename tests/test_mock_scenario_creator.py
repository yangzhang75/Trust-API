"""Scenario B (creator verification): policy unit tests + endpoint tests."""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.mock_helpers import FakeTrustClient, assessment
from trust_api.demo.platform.app import create_mock_app, get_trust_client
from trust_api.demo.platform.client import TrustError
from trust_api.demo.platform.config import MockSettings
from trust_api.demo.platform.policy import decide_creator

# --- policy unit tests ----------------------------------------------------


def test_creator_approves_only_gold() -> None:
    d = decide_creator(assessment("gold"))
    assert d.approved is True and d.reason == "gold_tier"


def test_creator_rejects_below_gold() -> None:
    for tier in ("silver", "bronze", "unknown"):
        d = decide_creator(assessment(tier))
        assert d.approved is False and d.reason == "tier_below_gold"


# --- endpoint tests -------------------------------------------------------


def _app_with(client: FakeTrustClient) -> TestClient:
    app = create_mock_app(MockSettings(trust_api_url="http://trust.test", trust_api_key="k"))
    app.dependency_overrides[get_trust_client] = lambda: client
    return TestClient(app)


def test_creator_endpoint_approves_gold_and_issues_proof() -> None:
    fake = FakeTrustClient({"0xG": assessment("gold")})
    body = _app_with(fake).post("/mock/creator/apply", json={"wallet": "0xG"}).json()
    assert body["approved"] is True and body["tier"] == "gold"
    assert body["proof"]["encoded"] == "proof-for-0xG"
    assert fake.proof_calls == ["0xG"]  # proof issued exactly once


def test_creator_endpoint_rejects_silver_without_proof() -> None:
    fake = FakeTrustClient({"0xS": assessment("silver")})
    body = _app_with(fake).post("/mock/creator/apply", json={"wallet": "0xS"}).json()
    assert body["approved"] is False and body["reason"] == "tier_below_gold"
    assert body["proof"] is None
    assert fake.proof_calls == []  # no proof issued on rejection


def test_creator_endpoint_invalid_wallet() -> None:
    fake = FakeTrustClient(errors={"0xbad": TrustError(400, "Invalid wallet address")})
    body = _app_with(fake).post("/mock/creator/apply", json={"wallet": "0xbad"}).json()
    assert body["approved"] is False and body["reason"] == "invalid_wallet"


class _ProofFailsClient(FakeTrustClient):
    """verify() succeeds (gold), but /proof/generate fails upstream."""

    def __init__(self) -> None:
        super().__init__({"0xG": assessment("gold")})

    def generate_proof(self, wallet: str, chains: list[str] | None = None) -> dict:
        raise TrustError(429, "Rate limit exceeded")


def test_creator_endpoint_502_when_proof_fails() -> None:
    resp = _app_with(_ProofFailsClient()).post("/mock/creator/apply", json={"wallet": "0xG"})
    assert resp.status_code == 502
    assert "proof failed" in resp.json()["detail"]
