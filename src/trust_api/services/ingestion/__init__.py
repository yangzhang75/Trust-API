"""Ingestion subsystem — real on-chain transaction ingestion (Week 2).

Exposes the provider client, the normalized `Transaction` DTO, typed
errors, and the fetch/ETL entry points used by the worker, seed, and jobs.
"""

from __future__ import annotations

from trust_api.services.ingestion.errors import (
    DataUnavailableError,
    IngestionError,
    ProviderError,
    ProviderRateLimitedError,
    ProviderTimeoutError,
)
from trust_api.services.ingestion.load import LoadResult, load_transactions
from trust_api.services.ingestion.models import Transaction
from trust_api.services.ingestion.provider import EtherscanClient
from trust_api.services.ingestion.service import fetch_wallet_history, ingest_wallet
from trust_api.services.ingestion.transform import normalize_transactions

__all__ = [
    "DataUnavailableError",
    "EtherscanClient",
    "IngestionError",
    "LoadResult",
    "ProviderError",
    "ProviderRateLimitedError",
    "ProviderTimeoutError",
    "Transaction",
    "fetch_wallet_history",
    "ingest_wallet",
    "load_transactions",
    "normalize_transactions",
]
