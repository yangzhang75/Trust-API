"""Ingestion subsystem.

Public surface kept stable for the rest of the app:
  * `WalletActivity` / `fetch_activity` — the deterministic stub feeding the
    still-stubbed features/scoring stages (Week 1 behavior, unchanged).
  * `Transaction`, the provider client, and typed errors — the real Week 2
    ingestion path (driven by the worker / seed / ETL).
"""

from __future__ import annotations

from trust_api.services.ingestion.activity import fetch_activity
from trust_api.services.ingestion.errors import (
    DataUnavailableError,
    IngestionError,
    ProviderError,
    ProviderRateLimitedError,
    ProviderTimeoutError,
)
from trust_api.services.ingestion.load import LoadResult, load_transactions
from trust_api.services.ingestion.models import Transaction, WalletActivity
from trust_api.services.ingestion.provider import EtherscanClient
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
    "WalletActivity",
    "fetch_activity",
    "load_transactions",
    "normalize_transactions",
]
