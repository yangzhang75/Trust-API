"""Scenario A (social login): policy unit tests + endpoint tests."""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.mock_helpers import FakeTrustClient, assessment
from trust_api.demo.platform.app import create_mock_app, get_trust_client
from trust_api.demo.platform.client import TrustError
from trust_api.demo.platform.config import MockSettings
from trust_api.demo.platform.policy import decide_login

# --- policy unit tests ----------------------------------------------------


def test_login_rejects_sybil_regardless_of_tier() -> None:
    d = decide_login(assessment("gold", flags=["sybil_suspected"]))
    assert d == decide_login(assessment("gold", flags=["sybil_suspected"]))
    assert d.accepted is False and d.reason == "sybil_suspected"


def test_login_accepts_silver_and_gold() -> None:
    for tier in ("silver", "gold"):
        d = decide_login(assessment(tier))
        assert d.accepted is True and d.reason == "tier_ok" and d.tier == tier


def test_login_flags_bronze_but_accepts() -> None:
    d = decide_login(assessment("bronze"))
    assert d.accepted is True and d.reason == "flagged_low_tier"


def test_login_rejects_unknown_tier() -> None:
    d = decide_login({"risk_flags": []})  # missing trust_tier
    assert d.accepted is False and d.reason == "unknown_tier" and d.tier == "unknown"


# --- endpoint tests -------------------------------------------------------


def _app_with(client: FakeTrustClient) -> TestClient:
    app = create_mock_app(MockSettings(trust_api_url="http://trust.test", trust_api_key="k"))
    app.dependency_overrides[get_trust_client] = lambda: client
    return TestClient(app)


def test_login_endpoint_accepts_silver() -> None:
    tc = _app_with(FakeTrustClient({"0xA": assessment("silver")}))
    body = tc.post("/mock/login", json={"wallet": "0xA"}).json()
    assert body == {"accepted": True, "tier": "silver", "reason": "tier_ok"}


def test_login_endpoint_rejects_sybil() -> None:
    tc = _app_with(FakeTrustClient({"0xB": assessment("bronze", flags=["sybil_suspected"])}))
    body = tc.post("/mock/login", json={"wallet": "0xB"}).json()
    assert body["accepted"] is False and body["reason"] == "sybil_suspected"


def test_login_endpoint_treats_invalid_wallet_as_rejection() -> None:
    tc = _app_with(FakeTrustClient(errors={"0xbad": TrustError(400, "Invalid wallet address")}))
    body = tc.post("/mock/login", json={"wallet": "0xbad"}).json()
    assert body == {"accepted": False, "tier": "invalid", "reason": "invalid_wallet"}


def test_login_endpoint_502_on_upstream_failure() -> None:
    tc = _app_with(FakeTrustClient(errors={"0xC": TrustError(429, "Rate limit exceeded")}))
    resp = tc.post("/mock/login", json={"wallet": "0xC"})
    assert resp.status_code == 502
    assert "Trust API unavailable" in resp.json()["detail"]
