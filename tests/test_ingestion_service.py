"""Tests for the ingestion service: caching, errors, and ETL orchestration."""

from __future__ import annotations

import httpx
import pytest
import respx
from redis.exceptions import RedisError
from sqlalchemy.orm import Session

from trust_api.config import Settings
from trust_api.schemas.verify import Chain
from trust_api.services.ingestion.errors import ProviderError
from trust_api.services.ingestion.service import fetch_wallet_history, ingest_wallet

BASE = "https://api.etherscan.io/v2/api"
WALLET = "0x52908400098527886E0F7030069857D2E4169EE7"


def _settings(**kw) -> Settings:
    base = dict(
        etherscan_api_key="test-provider-key",
        etherscan_base_url=BASE,
        ingestion_backoff_seconds=0,
        ingestion_cache_ttl_seconds=0,  # default: caching off unless a cache is injected
    )
    base.update(kw)
    return Settings(**base)


def _raw(i: int = 0) -> dict:
    return {
        "hash": f"0x{i:064x}",
        "from": WALLET.lower(),
        "to": "0x000000000000000000000000000000000000dead",
        "value": "1000000000000000000",
        "timeStamp": str(1_700_000_000 + i),
        "blockNumber": str(18_000_000 + i),
        "contractAddress": "",
    }


def _payload(*rows: dict) -> dict:
    return {"status": "1", "message": "OK", "result": list(rows)}


class FakeAsyncCache:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    async def get(self, key: str):
        return self.store.get(key)

    async def set(self, key: str, value, ex=None) -> None:
        self.store[key] = value


class FailingAsyncCache:
    """Simulates an unreachable Redis: every op raises."""

    async def get(self, key: str):
        raise RedisError("redis down")

    async def set(self, key: str, value, ex=None) -> None:
        raise RedisError("redis down")


async def test_fetch_requires_configured_provider() -> None:
    with pytest.raises(ProviderError):
        await fetch_wallet_history(WALLET, Chain.ethereum, settings=_settings(etherscan_api_key=""))


async def test_fetch_rejects_unsupported_chain(monkeypatch) -> None:
    monkeypatch.setattr(
        "trust_api.services.ingestion.service.EtherscanClient.supports",
        staticmethod(lambda chain: False),
    )
    with pytest.raises(ProviderError):
        await fetch_wallet_history(WALLET, Chain.ethereum, settings=_settings())


@respx.mock
async def test_fetch_caches_and_serves_from_cache() -> None:
    route = respx.get(BASE).mock(return_value=httpx.Response(200, json=_payload(_raw(1))))
    cache = FakeAsyncCache()
    settings = _settings(ingestion_cache_ttl_seconds=3600)

    first = await fetch_wallet_history(WALLET, Chain.ethereum, settings=settings, cache=cache)
    assert len(first) == 1
    assert route.call_count == 1
    assert cache.store  # cache populated

    # Second call is served from cache — no second HTTP request.
    second = await fetch_wallet_history(WALLET, Chain.ethereum, settings=settings, cache=cache)
    assert [t.tx_hash for t in second] == [t.tx_hash for t in first]
    assert route.call_count == 1


@respx.mock
async def test_fetch_degrades_gracefully_when_cache_unavailable() -> None:
    # Redis down: ingestion must still fetch and return, not crash.
    route = respx.get(BASE).mock(return_value=httpx.Response(200, json=_payload(_raw(1))))
    settings = _settings(ingestion_cache_ttl_seconds=3600)

    result = await fetch_wallet_history(
        WALLET, Chain.ethereum, settings=settings, cache=FailingAsyncCache()
    )
    assert len(result) == 1
    assert route.call_count == 1  # cache failure did not block the provider call


@respx.mock
async def test_fetch_uses_injected_client() -> None:
    import httpx as _httpx

    from trust_api.services.ingestion.provider import EtherscanClient

    respx.get(BASE).mock(return_value=httpx.Response(200, json=_payload(_raw(1))))
    client = EtherscanClient(_settings(), client=_httpx.AsyncClient())
    result = await fetch_wallet_history(WALLET, Chain.ethereum, settings=_settings(), client=client)
    assert len(result) == 1
    await client._client.aclose()


def test_build_cache_returns_client_when_enabled() -> None:
    from trust_api.services.ingestion.service import _build_cache

    assert _build_cache(_settings(ingestion_cache_ttl_seconds=0)) is None
    cache = _build_cache(_settings(ingestion_cache_ttl_seconds=60))
    assert cache is not None


def test_encode_decode_round_trip() -> None:
    from datetime import UTC, datetime

    from trust_api.services.ingestion.models import Transaction
    from trust_api.services.ingestion.service import _decode, _encode

    txs = [
        Transaction(
            chain=Chain.ethereum,
            tx_hash="0x" + "a" * 64,
            block_number=18_000_000,
            block_time=datetime(2023, 11, 14, 12, 0, tzinfo=UTC),
            value_wei=2**256 - 1,  # full uint256 must survive JSON round-trip
            direction="in",
            counterparty=None,  # null counterparty must round-trip
        )
    ]
    assert _decode(_encode(txs)) == txs


@respx.mock
async def test_ingest_wallet_persists(db_session: Session) -> None:
    respx.get(BASE).mock(return_value=httpx.Response(200, json=_payload(_raw(1), _raw(2))))
    result = await ingest_wallet(db_session, WALLET, Chain.ethereum, settings=_settings())
    assert result.inserted == 2
    assert result.total == 2
