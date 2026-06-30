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


def test_supports_only_ethereum() -> None:
    assert EtherscanClient.supports(Chain.ethereum) is True
