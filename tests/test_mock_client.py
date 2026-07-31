"""Tests for the mock platform's Trust API client (via httpx.MockTransport)."""

from __future__ import annotations

import json

import httpx
import pytest

from trust_api.demo.platform.client import TrustClient, TrustError


def _client(handler) -> TrustClient:
    transport = httpx.MockTransport(handler)
    hc = httpx.Client(transport=transport, base_url="http://trust.test")
    return TrustClient("http://trust.test", "secret-key", client=hc)


def test_verify_returns_body_and_sends_auth() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/verify"
        assert request.headers["x-api-key"] == "secret-key"
        assert json.loads(request.content) == {"wallet": "0xabc"}
        return httpx.Response(200, json={"trust_tier": "gold", "risk_flags": []})

    assert _client(handler).verify("0xabc")["trust_tier"] == "gold"


def test_verify_includes_chains_when_given() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert json.loads(request.content)["chains"] == ["arbitrum"]
        return httpx.Response(200, json={"ok": True})

    _client(handler).verify("0xabc", chains=["arbitrum"])


def test_generate_proof_hits_proof_endpoint_with_chains() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/proof/generate"
        assert json.loads(request.content)["chains"] == ["ethereum"]
        return httpx.Response(200, json={"encoded": "abc", "summary": "…"})

    assert _client(handler).generate_proof("0xabc", chains=["ethereum"])["encoded"] == "abc"


def test_error_with_json_detail() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"detail": "Invalid wallet address"})

    with pytest.raises(TrustError) as exc:
        _client(handler).verify("0xnothex")
    assert exc.value.status_code == 400
    assert "Invalid wallet" in exc.value.detail


def test_error_with_non_json_body() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="internal boom")

    with pytest.raises(TrustError) as exc:
        _client(handler).verify("0xabc")
    assert exc.value.status_code == 500
    assert "boom" in exc.value.detail


def test_connection_failure_becomes_trust_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    with pytest.raises(TrustError) as exc:
        _client(handler).verify("0xabc")
    assert exc.value.status_code == 0


def test_close_is_safe() -> None:
    _client(lambda request: httpx.Response(200, json={})).close()
