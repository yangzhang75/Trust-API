"""Tests for the Etherscan provider client (mocked HTTP — never live)."""

from __future__ import annotations

import httpx
import pytest
import respx

from trust_api.config import Settings
from trust_api.schemas.verify import Chain
from trust_api.services.ingestion.errors import DataUnavailableError, ProviderError
from trust_api.services.ingestion.provider import EtherscanClient

BASE = "https://api.etherscan.io/v2/api"
ADDR = "0x52908400098527886E0F7030069857D2E4169EE7"


def _settings(**kw) -> Settings:
    # backoff 0 so retry tests don't actually sleep
    base = dict(
        etherscan_api_key="test-provider-key",
        etherscan_base_url=BASE,
        ingestion_backoff_seconds=0,
        ingestion_max_attempts=3,
    )
    base.update(kw)
    return Settings(**base)


def _txlist(*results: dict) -> dict:
    return {"status": "1", "message": "OK", "result": list(results)}


@respx.mock
async def test_happy_path_returns_raw_transactions() -> None:
    raw = {
        "hash": "0xabc",
        "from": ADDR.lower(),
        "to": "0xdef",
        "value": "10",
        "timeStamp": "1700000000",
        "blockNumber": "100",
    }
    respx.get(BASE).mock(return_value=httpx.Response(200, json=_txlist(raw)))

    async with EtherscanClient(_settings()) as client:
        result = await client.get_normal_transactions(ADDR, Chain.ethereum)

    assert result == [raw]


@respx.mock
async def test_no_transactions_found_returns_empty() -> None:
    respx.get(BASE).mock(
        return_value=httpx.Response(
            200, json={"status": "0", "message": "No transactions found", "result": []}
        )
    )
    async with EtherscanClient(_settings()) as client:
        assert await client.get_normal_transactions(ADDR, Chain.ethereum) == []


@respx.mock
async def test_persistent_429_retries_then_raises_data_unavailable() -> None:
    route = respx.get(BASE).mock(return_value=httpx.Response(429, text="rate limited"))
    with pytest.raises(DataUnavailableError):
        async with EtherscanClient(_settings(ingestion_max_attempts=3)) as client:
            await client.get_normal_transactions(ADDR, Chain.ethereum)
    assert route.call_count == 3  # retried up to max_attempts


@respx.mock
async def test_rate_limit_message_recovers_after_retry() -> None:
    rate_limited = httpx.Response(
        200, json={"status": "0", "message": "NOTOK", "result": "Max rate limit reached"}
    )
    ok = httpx.Response(200, json=_txlist())
    respx.get(BASE).mock(side_effect=[rate_limited, ok])

    async with EtherscanClient(_settings()) as client:
        # First call is rate-limited, retry succeeds with an empty list.
        assert await client.get_normal_transactions(ADDR, Chain.ethereum) == []


@respx.mock
async def test_timeout_is_retried_then_surfaced() -> None:
    respx.get(BASE).mock(side_effect=httpx.ReadTimeout("timed out"))
    with pytest.raises(DataUnavailableError):
        async with EtherscanClient(_settings(ingestion_max_attempts=2)) as client:
            await client.get_normal_transactions(ADDR, Chain.ethereum)


@respx.mock
async def test_provider_error_not_retried() -> None:
    route = respx.get(BASE).mock(
        return_value=httpx.Response(
            200, json={"status": "0", "message": "Invalid API Key", "result": "bad"}
        )
    )
    with pytest.raises(ProviderError):
        async with EtherscanClient(_settings()) as client:
            await client.get_normal_transactions(ADDR, Chain.ethereum)
    assert route.call_count == 1  # non-transient: no retry


@respx.mock
async def test_http_500_is_transient_then_data_unavailable() -> None:
    route = respx.get(BASE).mock(return_value=httpx.Response(503, text="upstream down"))
    with pytest.raises(DataUnavailableError):
        async with EtherscanClient(_settings(ingestion_max_attempts=2)) as client:
            await client.get_normal_transactions(ADDR, Chain.ethereum)
    assert route.call_count == 2  # 5xx retried


@respx.mock
async def test_unexpected_status_code_is_provider_error() -> None:
    route = respx.get(BASE).mock(return_value=httpx.Response(403, text="forbidden"))
    with pytest.raises(ProviderError):
        async with EtherscanClient(_settings()) as client:
            await client.get_normal_transactions(ADDR, Chain.ethereum)
    assert route.call_count == 1  # 4xx (non-429) not retried


@respx.mock
async def test_transport_error_is_retried() -> None:
    respx.get(BASE).mock(side_effect=httpx.ConnectError("connection refused"))
    with pytest.raises(DataUnavailableError):
        async with EtherscanClient(_settings(ingestion_max_attempts=2)) as client:
            await client.get_normal_transactions(ADDR, Chain.ethereum)


@respx.mock
async def test_generic_http_error_is_provider_error() -> None:
    route = respx.get(BASE).mock(side_effect=httpx.HTTPError("boom"))
    with pytest.raises(ProviderError):
        async with EtherscanClient(_settings()) as client:
            await client.get_normal_transactions(ADDR, Chain.ethereum)
    assert route.call_count == 1  # non-transport HTTP error not retried


@respx.mock
async def test_injected_client_is_not_closed_by_context() -> None:
    raw = {
        "hash": "0x1",
        "from": ADDR.lower(),
        "to": "0x2",
        "value": "0",
        "timeStamp": "1700000000",
        "blockNumber": "1",
    }
    respx.get(BASE).mock(return_value=httpx.Response(200, json=_txlist(raw)))
    injected = httpx.AsyncClient()
    async with EtherscanClient(_settings(), client=injected) as client:
        assert await client.get_normal_transactions(ADDR, Chain.ethereum) == [raw]
    assert not injected.is_closed  # we don't own it, so we don't close it
    await injected.aclose()


def test_unsupported_chain_raises_provider_error(monkeypatch) -> None:
    from trust_api.services.ingestion import provider as provider_mod

    monkeypatch.setattr(provider_mod, "_CHAIN_IDS", {})  # simulate no supported chains
    client = EtherscanClient(_settings())
    with pytest.raises(ProviderError):
        client._chain_id(Chain.ethereum)


async def test_request_without_initialized_client_raises() -> None:
    client = EtherscanClient(_settings())  # no async-with, no injected client
    with pytest.raises(ProviderError):
        await client.get_normal_transactions(ADDR, Chain.ethereum)


def test_supports_ethereum_and_arbitrum() -> None:
    assert EtherscanClient.supports(Chain.ethereum) is True
    assert EtherscanClient.supports(Chain.arbitrum) is True


@respx.mock
async def test_chainid_param_matches_chain() -> None:
    route = respx.get(BASE).mock(return_value=httpx.Response(200, json=_txlist()))
    async with EtherscanClient(_settings()) as client:
        await client.get_normal_transactions(ADDR, Chain.ethereum)
        await client.get_normal_transactions(ADDR, Chain.arbitrum)
    assert route.calls[0].request.url.params["chainid"] == "1"  # ethereum
    assert route.calls[1].request.url.params["chainid"] == "42161"  # arbitrum
