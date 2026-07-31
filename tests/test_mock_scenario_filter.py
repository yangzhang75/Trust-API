"""Scenario C (bot filtering): policy unit tests + batch endpoint tests."""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.mock_helpers import FakeTrustClient, assessment
from trust_api.demo.platform.app import create_mock_app, get_trust_client
from trust_api.demo.platform.client import TrustError
from trust_api.demo.platform.config import MockSettings
from trust_api.demo.platform.policy import decide_filter

# --- policy unit tests ----------------------------------------------------


def test_filter_removes_sybil() -> None:
    d = decide_filter(assessment("silver", likelihood="high", flags=["sybil_suspected"]))
    assert d.keep is False and d.reason == "sybil_suspected"


def test_filter_removes_low_likelihood() -> None:
    d = decide_filter(assessment("bronze", likelihood="low"))
    assert d.keep is False and d.reason == "low_human_likelihood"


def test_filter_keeps_plausible_human() -> None:
    d = decide_filter(assessment("silver", likelihood="high"))
    assert d.keep is True and d.reason == "looks_human"


# --- endpoint tests -------------------------------------------------------


def _app_with(client: FakeTrustClient) -> TestClient:
    app = create_mock_app(MockSettings(trust_api_url="http://trust.test", trust_api_key="k"))
    app.dependency_overrides[get_trust_client] = lambda: client
    return TestClient(app)


def test_filter_batch_partitions_wallets() -> None:
    fake = FakeTrustClient(
        {
            "0xhuman": assessment("gold", likelihood="high"),
            "0xbot": assessment("bronze", likelihood="low"),
            "0xsybil": assessment("silver", likelihood="high", flags=["sybil_suspected"]),
        }
    )
    body = (
        _app_with(fake)
        .post("/mock/filter/batch", json={"wallets": ["0xhuman", "0xbot", "0xsybil"]})
        .json()
    )
    kept = {e["wallet"] for e in body["kept"]}
    removed = {e["wallet"]: e["reason"] for e in body["removed"]}
    assert kept == {"0xhuman"}
    assert removed == {"0xbot": "low_human_likelihood", "0xsybil": "sybil_suspected"}


def test_filter_batch_isolates_upstream_errors() -> None:
    """A rate-limited / invalid wallet is marked removed, not fatal to the batch."""
    fake = FakeTrustClient(
        {"0xok": assessment("gold", likelihood="high")},
        errors={
            "0xbad": TrustError(400, "Invalid wallet address"),
            "0x429": TrustError(429, "Rate limit exceeded"),
        },
    )
    body = (
        _app_with(fake)
        .post("/mock/filter/batch", json={"wallets": ["0xok", "0xbad", "0x429"]})
        .json()
    )
    assert [e["wallet"] for e in body["kept"]] == ["0xok"]
    removed = {e["wallet"]: e["reason"] for e in body["removed"]}
    assert removed == {"0xbad": "invalid_wallet", "0x429": "trust_api_error"}


def test_filter_batch_empty() -> None:
    body = _app_with(FakeTrustClient()).post("/mock/filter/batch", json={"wallets": []}).json()
    assert body == {"kept": [], "removed": []}
