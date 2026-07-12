"""Tests for in-process scoring metrics and the /metrics endpoint."""

from __future__ import annotations

from datetime import UTC, datetime

import httpx
import respx
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from trust_api import pipeline
from trust_api.config import Settings
from trust_api.core.metrics import METRICS, render_prometheus

BASE = "https://api.etherscan.io/v2/api"
W1 = "0x52908400098527886E0F7030069857D2E4169EE7"
NOW = datetime(2026, 1, 1, tzinfo=UTC)


def test_record_and_snapshot() -> None:
    METRICS.reset()
    METRICS.record(ok=True, duration_seconds=0.1)
    METRICS.record(ok=True, duration_seconds=0.3)
    METRICS.record(ok=False, duration_seconds=0.2)
    snap = METRICS.snapshot()
    assert snap["wallets_scored_total"] == 2
    assert snap["wallets_failed_total"] == 1
    assert snap["scoring_duration_seconds_count"] == 3
    assert snap["scoring_duration_seconds_min"] == 0.1
    assert snap["scoring_duration_seconds_max"] == 0.3


def test_render_prometheus_format() -> None:
    METRICS.reset()
    METRICS.record(ok=True, duration_seconds=0.5)
    text = render_prometheus()
    assert "# TYPE wallets_scored_total counter" in text
    assert "wallets_scored_total 1" in text
    assert "scoring_duration_seconds_avg" in text


def test_metrics_endpoint_empty(client: TestClient) -> None:
    METRICS.reset()
    resp = client.get("/metrics")
    assert resp.status_code == 200
    assert "text/plain" in resp.headers["content-type"]
    assert "wallets_scored_total 0" in resp.text


def _ok(request: httpx.Request) -> httpx.Response:
    addr = request.url.params.get("address", "")
    raw = {
        "hash": "0x" + addr[2:10].rjust(64, "0"),
        "from": addr.lower(),
        "to": "0x000000000000000000000000000000000000dead",
        "value": "1",
        "timeStamp": "1700000000",
        "blockNumber": "18000000",
        "contractAddress": "",
    }
    return httpx.Response(200, json={"status": "1", "message": "OK", "result": [raw]})


@respx.mock
def test_metrics_increment_after_a_run(client: TestClient, db_session: Session) -> None:
    METRICS.reset()
    respx.get(BASE).mock(side_effect=_ok)
    settings = Settings(
        etherscan_api_key="k",
        etherscan_base_url=BASE,
        ingestion_backoff_seconds=0,
        ingestion_cache_ttl_seconds=0,
    )
    pipeline.score_wallet(db_session, W1, settings, now=NOW)
    body = client.get("/metrics").text
    assert "wallets_scored_total 1" in body  # counter reflects the run
