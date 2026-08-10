"""Hybrid re-score: the mock's background job + /mock/rescore endpoint.

Covers account registration on login, the batch re-score, and retroactive
suspension when a wallet flips to sybil/bronze under the graph-aware batch."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from tests.conftest import TEST_API_KEY
from tests.mock_helpers import FakeTrustClient, assessment
from trust_api.demo.platform.app import create_mock_app, get_trust_client
from trust_api.demo.platform.config import MockSettings
from trust_api.demo.platform.hybrid import rescore_recent
from trust_api.demo.platform.metrics import MetricsStore

AUTH = {"X-API-Key": TEST_API_KEY}


# --- store account tracking ----------------------------------------------


def test_upsert_and_recent_active_accounts() -> None:
    store = MetricsStore(":memory:")
    now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    store.upsert_account("0xA", "silver", now=now.isoformat())
    store.upsert_account("0xB", "gold", now=(now - timedelta(minutes=30)).isoformat())
    # only 0xA is within the 15-minute window
    assert store.recent_active_accounts(15, now=now) == ["0xA"]
    assert set(store.recent_active_accounts(60, now=now)) == {"0xA", "0xB"}


def test_suspend_account_updates_status() -> None:
    store = MetricsStore(":memory:")
    store.upsert_account("0xA", "silver")
    store.suspend_account("0xA", "sybil_suspected_on_batch_rescore")
    acct = store.account("0xA")
    assert acct["status"] == "suspended"
    assert acct["suspended_reason"] == "sybil_suspected_on_batch_rescore"
    # a later accepted login reactivates it
    store.upsert_account("0xA", "gold")
    assert store.account("0xA")["status"] == "active"
    assert store.account("0xunknown") is None


# --- the re-score job ----------------------------------------------------


def test_rescore_suspends_wallets_that_flip() -> None:
    store = MetricsStore(":memory:")
    now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    for w in ("0xhuman", "0xsybil", "0xbronze"):
        store.upsert_account(w, "silver", now=now.isoformat())
    # Batch re-score (graph-aware) now flips two of them.
    client = FakeTrustClient(
        {
            "0xhuman": assessment("gold", likelihood="high"),
            "0xsybil": assessment("silver", flags=["sybil_suspected"]),
            "0xbronze": assessment("bronze", likelihood="low"),
        }
    )
    result = rescore_recent(store, client, now=now)

    assert result["rescored"] == 3
    suspended = {s["wallet"]: s["reason"] for s in result["suspended"]}
    assert suspended == {
        "0xsybil": "sybil_suspected_on_batch_rescore",
        "0xbronze": "bronze_on_batch_rescore",
    }
    assert store.account("0xhuman")["status"] == "active"
    assert store.account("0xsybil")["status"] == "suspended"
    assert client.batch_calls == [["0xhuman", "0xsybil", "0xbronze"]]  # one batch call


def test_rescore_noop_when_no_recent_accounts() -> None:
    store = MetricsStore(":memory:")
    client = FakeTrustClient()
    assert rescore_recent(store, client) == {"rescored": 0, "suspended": []}
    assert client.batch_calls == []  # nothing to re-score -> no batch call


# --- endpoint: login registers, /mock/rescore suspends -------------------


def _app_with(client: FakeTrustClient) -> TestClient:
    app = create_mock_app(MockSettings(trust_api_url="http://trust.test", trust_api_key="k"))
    app.dependency_overrides[get_trust_client] = lambda: client
    return TestClient(app)


def test_login_registers_then_rescore_suspends_end_to_end() -> None:
    # Instant login: single /verify says silver (no sybil flag) -> accepted.
    # The graph-aware batch re-score reveals sybil -> retroactively suspended.
    client = FakeTrustClient(
        {"0xW": assessment("silver")},
        batch_assessments={"0xW": assessment("silver", flags=["sybil_suspected"])},
    )
    tc = _app_with(client)

    login = tc.post("/mock/login", json={"wallet": "0xW"}).json()
    assert login["accepted"] is True  # instant decision let it in

    body = tc.post("/mock/rescore").json()
    assert body["rescored"] == 1
    assert body["suspended"] == [
        {"wallet": "0xW", "reason": "sybil_suspected_on_batch_rescore", "tier": "silver"}
    ]


def test_rejected_login_is_not_registered() -> None:
    # A sybil rejected at login never becomes an account, so rescore is a no-op.
    client = FakeTrustClient({"0xR": assessment("bronze", flags=["sybil_suspected"])})
    tc = _app_with(client)
    assert tc.post("/mock/login", json={"wallet": "0xR"}).json()["accepted"] is False
    assert tc.post("/mock/rescore").json() == {"rescored": 0, "suspended": []}
