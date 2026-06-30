"""Ingestion service: the real fetch path + ETL orchestration.

`fetch_wallet_history` is the Week 2 replacement for the stub fetch — it
pulls a wallet's normalized transaction history from the provider, with a
Redis cache so the same wallet isn't re-fetched on every call.
`ingest_wallet` runs the full E→T→L: fetch, then idempotently load to
Postgres. Both are async (the provider client is async).
"""

from __future__ import annotations

import json
from datetime import datetime

import redis.asyncio as aioredis
from redis.exceptions import RedisError

from trust_api.config import Settings, get_settings
from trust_api.core.logging import get_logger
from trust_api.schemas.verify import Chain
from trust_api.services.ingestion.errors import ProviderError
from trust_api.services.ingestion.load import LoadResult, load_transactions
from trust_api.services.ingestion.models import Transaction
from trust_api.services.ingestion.provider import EtherscanClient
from trust_api.services.ingestion.transform import normalize_transactions

logger = get_logger(__name__)


def _cache_key(wallet: str, chain: Chain) -> str:
    return f"ingest:{chain}:{wallet.lower()}"


def _encode(txs: list[Transaction]) -> str:
    return json.dumps(
        [
            {
                "chain": tx.chain.value,
                "tx_hash": tx.tx_hash,
                "block_number": tx.block_number,
                "block_time": tx.block_time.isoformat(),
                "value_wei": str(tx.value_wei),  # avoid JSON int overflow
                "direction": tx.direction,
                "counterparty": tx.counterparty,
            }
            for tx in txs
        ]
    )


def _decode(blob: str | bytes) -> list[Transaction]:
    return [
        Transaction(
            chain=Chain(d["chain"]),
            tx_hash=d["tx_hash"],
            block_number=int(d["block_number"]),
            block_time=datetime.fromisoformat(d["block_time"]),
            value_wei=int(d["value_wei"]),
            direction=d["direction"],
            counterparty=d["counterparty"],
        )
        for d in json.loads(blob)
    ]


def _build_cache(settings: Settings) -> aioredis.Redis | None:
    """Return an async Redis client, or None when caching is disabled."""
    if settings.ingestion_cache_ttl_seconds <= 0:
        return None
    return aioredis.from_url(settings.redis_url)


async def _cache_get(cache: aioredis.Redis, key: str) -> str | bytes | None:
    """Read from cache, degrading gracefully if Redis is unavailable."""
    try:
        return await cache.get(key)
    except RedisError as exc:
        logger.warning("ingestion cache get failed (%s); bypassing cache", exc)
        return None


async def _cache_set(cache: aioredis.Redis, key: str, value: str, ttl: int) -> None:
    """Write to cache, degrading gracefully if Redis is unavailable."""
    try:
        await cache.set(key, value, ex=ttl)
    except RedisError as exc:
        logger.warning("ingestion cache set failed (%s); continuing", exc)


async def fetch_wallet_history(
    wallet: str,
    chain: Chain,
    *,
    settings: Settings | None = None,
    client: EtherscanClient | None = None,
    cache: aioredis.Redis | None = None,
) -> list[Transaction]:
    """Fetch normalized transaction history for ``wallet`` on ``chain``.

    Serves from the Redis cache on a hit; otherwise calls the provider,
    normalizes, caches, and returns. Raises ProviderError for an
    unsupported chain or when no provider is configured.
    """
    settings = settings or get_settings()
    if not EtherscanClient.supports(chain):
        raise ProviderError(f"Ingestion not supported for chain: {chain}")
    if client is None and not settings.ingestion_provider_configured:
        raise ProviderError("No ingestion provider configured (set ETHERSCAN_API_KEY)")

    cache = cache if cache is not None else _build_cache(settings)
    key = _cache_key(wallet, chain)

    if cache is not None:
        cached = await _cache_get(cache, key)
        if cached is not None:
            logger.debug("ingestion cache hit for %s", key)
            return _decode(cached)

    if client is not None:
        raw = await client.get_normal_transactions(wallet, chain)
    else:
        async with EtherscanClient(settings) as owned:
            raw = await owned.get_normal_transactions(wallet, chain)

    txs = normalize_transactions(raw, wallet, chain)

    if cache is not None:
        await _cache_set(cache, key, _encode(txs), settings.ingestion_cache_ttl_seconds)

    return txs


async def ingest_wallet(
    session,
    wallet: str,
    chain: Chain = Chain.ethereum,
    *,
    settings: Settings | None = None,
    client: EtherscanClient | None = None,
    cache: aioredis.Redis | None = None,
) -> LoadResult:
    """Run the full ETL for one wallet: fetch -> transform -> idempotent load."""
    txs = await fetch_wallet_history(wallet, chain, settings=settings, client=client, cache=cache)
    result = load_transactions(session, wallet, chain, txs)
    logger.info(
        "ingested wallet=%s chain=%s inserted=%d total=%d",
        wallet,
        chain,
        result.inserted,
        result.total,
    )
    return result
