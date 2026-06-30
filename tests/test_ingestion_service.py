"""Tests for the ingestion service: caching, errors, and ETL orchestration."""

from __future__ import annotations

import httpx
import pytest
import respx
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


async def test_fetch_requires_configured_provider() -> None:
    with pytest.raises(ProviderError):
        await fetch_wallet_history(WALLET, Chain.ethereum, settings=_settings(etherscan_api_key=""))


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
async def test_ingest_wallet_persists(db_session: Session) -> None:
    respx.get(BASE).mock(return_value=httpx.Response(200, json=_payload(_raw(1), _raw(2))))
    result = await ingest_wallet(db_session, WALLET, Chain.ethereum, settings=_settings())
    assert result.inserted == 2
    assert result.total == 2
