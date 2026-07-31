"""Tests for the traffic simulator (run() driven by a TestClient)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.mock_helpers import FakeTrustClient, assessment
from trust_api.demo.platform.app import create_mock_app, get_trust_client
from trust_api.demo.platform.config import MockSettings
from trust_api.demo.platform.simulate import run, sample_wallets


def test_sample_wallets_returns_human_sybil_mix() -> None:
    wallets = sample_wallets(6, path="data/labeled_wallets.json")
    assert len(wallets) == 6
    labels = {w["label"] for w in wallets}
    assert labels == {"human", "sybil"}  # mix of both
    assert all(w["address"].startswith("0x") for w in wallets)


def test_run_drives_all_scenarios_and_prints_stats() -> None:
    wallets = [
        {"address": "0xh1", "label": "human"},
        {"address": "0xh2", "label": "human"},
        {"address": "0xs1", "label": "sybil"},
    ]
    fake = FakeTrustClient(
        {
            "0xh1": assessment("gold", likelihood="high"),
            "0xh2": assessment("silver", likelihood="high"),
            "0xs1": assessment("bronze", likelihood="low", flags=["sybil_suspected"]),
        }
    )
    app = create_mock_app(MockSettings(trust_api_url="http://trust.test", trust_api_key="k"))
    app.dependency_overrides[get_trust_client] = lambda: fake
    http = TestClient(app)

    lines: list[str] = []
    stats = run(http, wallets, out=lines.append)

    # login: h1(accept) h2(accept) s1(reject) -> 2/3 accepted
    assert stats["login"]["total"] == 3 and stats["login"]["accepted"] == 2
    # creator: only h1 gold approved
    assert stats["creator"]["total"] == 3 and stats["creator"]["accepted"] == 1
    # filter batch: keep h1,h2; remove s1
    assert stats["filter"]["total"] == 3 and stats["filter"]["accepted"] == 2

    text = "\n".join(lines)
    assert "Traffic simulator" in text
    assert "input mix: 2 human / 1 sybil" in text
    assert "[login]" in text and "[creator]" in text and "[filter]" in text
