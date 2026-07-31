"""Metrics store unit tests + /mock/stats endpoint test."""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.mock_helpers import FakeTrustClient, assessment
from trust_api.demo.platform.app import create_mock_app, get_trust_client
from trust_api.demo.platform.config import MockSettings
from trust_api.demo.platform.metrics import MetricsStore

# --- store unit tests -----------------------------------------------------


def test_stats_aggregates_totals_rate_latency_and_breakdowns() -> None:
    store = MetricsStore(":memory:")
    store.record(
        scenario="login",
        wallet="0x1",
        accepted=True,
        tier="gold",
        reason="tier_ok",
        latency_ms=10.0,
    )
    store.record(
        scenario="login",
        wallet="0x2",
        accepted=False,
        tier="bronze",
        reason="sybil_suspected",
        latency_ms=20.0,
    )
    s = store.stats()["login"]
    assert s["total"] == 2
    assert s["accepted"] == 1 and s["rejected"] == 1
    assert s["acceptance_rate"] == 0.5
    assert s["avg_latency_ms"] == 15.0
    assert s["tiers"] == {"gold": 1, "bronze": 1}
    assert s["reasons"] == {"tier_ok": 1, "sybil_suspected": 1}
    store.close()


def test_stats_empty_is_empty_dict() -> None:
    assert MetricsStore(":memory:").stats() == {}


def test_metrics_persist_to_file_across_instances(tmp_path) -> None:
    path = str(tmp_path / "m.db")
    first = MetricsStore(path)
    first.record(
        scenario="filter",
        wallet="0x9",
        accepted=True,
        tier="silver",
        reason="looks_human",
        latency_ms=5.0,
        ts="2026-01-01T00:00:00+00:00",  # explicit ts branch
    )
    first.close()

    reopened = MetricsStore(path)
    assert reopened.stats()["filter"]["total"] == 1
    reopened.close()


# --- /mock/stats endpoint -------------------------------------------------


def test_stats_endpoint_reflects_real_traffic() -> None:
    fake = FakeTrustClient(
        {
            "0xg": assessment("gold", likelihood="high"),
            "0xs": assessment("silver", likelihood="high"),
            "0xb": assessment("bronze", likelihood="low", flags=["sybil_suspected"]),
        }
    )
    app = create_mock_app(MockSettings(trust_api_url="http://trust.test", trust_api_key="k"))
    app.dependency_overrides[get_trust_client] = lambda: fake
    c = TestClient(app)

    c.post("/mock/login", json={"wallet": "0xg"})  # accept
    c.post("/mock/login", json={"wallet": "0xb"})  # reject (sybil)
    c.post("/mock/creator/apply", json={"wallet": "0xg"})  # approve + proof
    c.post("/mock/creator/apply", json={"wallet": "0xs"})  # reject (silver)
    c.post("/mock/filter/batch", json={"wallets": ["0xg", "0xb"]})  # keep g, remove b

    stats = c.get("/mock/stats").json()
    login = stats["login"]
    assert (login["total"], login["accepted"], login["rejected"]) == (2, 1, 1)
    assert login["acceptance_rate"] == 0.5
    assert login["tiers"] == {"gold": 1, "bronze": 1}
    assert isinstance(login["avg_latency_ms"], float)
    assert stats["creator"]["total"] == 2 and stats["creator"]["accepted"] == 1
    assert stats["filter"]["total"] == 2 and stats["filter"]["accepted"] == 1
