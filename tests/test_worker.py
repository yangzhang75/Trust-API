"""Tests for the background ingestion worker's core pass."""

from __future__ import annotations

import httpx
import respx
from sqlalchemy.orm import Session

from trust_api.config import Settings
from trust_api.schemas.verify import Chain
from trust_api.worker import ingest_wallets

BASE = "https://api.etherscan.io/v2/api"
W1 = "0x52908400098527886E0F7030069857D2E4169EE7"
W2 = "0xde709f2102306220921060314715629080e2fb77"
OTHER = "0x000000000000000000000000000000000000dead"


def _settings() -> Settings:
    return Settings(
        etherscan_api_key="test-provider-key",
        etherscan_base_url=BASE,
        ingestion_backoff_seconds=0,
        ingestion_cache_ttl_seconds=0,
    )


def _row_for(address: str) -> dict:
    return {
        "hash": "0x" + "b" * 64,
        "from": address.lower(),
        "to": OTHER,
        "value": "1",
        "timeStamp": "1700000000",
        "blockNumber": "18000000",
        "contractAddress": "",
    }


@respx.mock
async def test_ingest_wallets_success(db_session: Session) -> None:
    def responder(request: httpx.Request) -> httpx.Response:
        addr = request.url.params.get("address", "")
        return httpx.Response(
            200, json={"status": "1", "message": "OK", "result": [_row_for(addr)]}
        )

    respx.get(BASE).mock(side_effect=responder)

    results = await ingest_wallets(db_session, [W1, W2], Chain.ethereum, settings=_settings())
    assert results == {W1: 1, W2: 1}


@respx.mock
async def test_ingest_wallets_isolates_failures(db_session: Session) -> None:
    # Provider returns a hard error: each wallet fails but the pass continues.
    respx.get(BASE).mock(
        return_value=httpx.Response(
            200, json={"status": "0", "message": "Invalid API Key", "result": "bad key"}
        )
    )
    results = await ingest_wallets(db_session, [W1, W2], Chain.ethereum, settings=_settings())
    assert results == {W1: None, W2: None}  # recorded as failed, no exception raised
