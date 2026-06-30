"""Typed errors for the ingestion subsystem.

These let callers (and the API layer) distinguish a transient provider
hiccup from a genuine failure, instead of leaking raw exceptions or 500s.
"""

from __future__ import annotations


class IngestionError(Exception):
    """Base class for all ingestion failures."""


class ProviderError(IngestionError):
    """The data provider returned a non-recoverable error (e.g. bad key)."""


class ProviderTimeoutError(IngestionError):
    """A provider call timed out. Transient — safe to retry."""


class ProviderRateLimitedError(IngestionError):
    """The provider rate-limited us (HTTP 429 / quota). Transient — back off."""


class DataUnavailableError(IngestionError):
    """Data genuinely could not be fetched after exhausting retries.

    The API layer maps this to a 503 rather than a 500.
    """
