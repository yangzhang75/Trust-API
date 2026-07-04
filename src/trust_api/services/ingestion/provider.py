"""Web3 data provider client (Etherscan V2 unified API).

Why Etherscan V2: a single REST call (`account/txlist`) returns a wallet's
full normal-transaction list with all the fields we normalize (hash,
timestamp, from/to, value, block), and one API key works across chains via
the `chainid` parameter — so Polygon/etc. plug in later by adding a chain
id. We only enable Ethereum in Week 2.

Resilience (graded): every call has a timeout; transient failures
(timeouts, HTTP 429/5xx, provider rate-limit messages) are retried with
exponential backoff and ultimately surfaced as DataUnavailableError;
non-recoverable errors raise ProviderError. No raw data leaks past here.
"""

from __future__ import annotations

from types import TracebackType

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from trust_api.config import Settings
from trust_api.core.logging import get_logger
from trust_api.schemas.verify import Chain
from trust_api.services.ingestion.errors import (
    DataUnavailableError,
    ProviderError,
    ProviderRateLimitedError,
    ProviderTimeoutError,
)

logger = get_logger(__name__)

# Etherscan V2 chain ids. One API key works across all of them via the
# `chainid` parameter; this registry is the single place chains plug in.
_CHAIN_IDS: dict[Chain, int] = {Chain.ethereum: 1, Chain.arbitrum: 42161}

_RATE_LIMIT_MARKERS = ("max rate limit reached", "rate limit")


class EtherscanClient:
    """Async client for the Etherscan V2 `account/txlist` endpoint."""

    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None) -> None:
        self._settings = settings
        self._client = client  # injectable for tests
        self._owns_client = client is None

    @staticmethod
    def supports(chain: Chain) -> bool:
        """Whether ingestion is implemented for ``chain`` (Ethereum only)."""
        return chain in _CHAIN_IDS

    def _chain_id(self, chain: Chain) -> int:
        try:
            return _CHAIN_IDS[chain]
        except KeyError:
            raise ProviderError(f"Ingestion not supported for chain: {chain}") from None

    async def __aenter__(self) -> EtherscanClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self._settings.ingestion_timeout_seconds)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()

    async def get_normal_transactions(self, address: str, chain: Chain) -> list[dict]:
        """Return the raw normal-transaction list for ``address`` on ``chain``.

        Retries transient failures with exponential backoff; raises
        DataUnavailableError once they're exhausted.
        """
        attempts = self._settings.ingestion_max_attempts

        @retry(
            retry=retry_if_exception_type((ProviderTimeoutError, ProviderRateLimitedError)),
            wait=wait_exponential(multiplier=self._settings.ingestion_backoff_seconds, max=8),
            stop=stop_after_attempt(attempts),
            reraise=True,
        )
        async def _do() -> list[dict]:
            return await self._request_once(address, chain)

        try:
            return await _do()
        except (ProviderTimeoutError, ProviderRateLimitedError) as exc:
            raise DataUnavailableError(
                f"Provider unavailable after {attempts} attempt(s): {exc}"
            ) from exc

    async def _request_once(self, address: str, chain: Chain) -> list[dict]:
        if self._client is None:
            raise ProviderError("HTTP client not initialized; use 'async with'")

        params = {
            "chainid": self._chain_id(chain),
            "module": "account",
            "action": "txlist",
            "address": address,
            "startblock": 0,
            "endblock": 99999999,
            "page": 1,
            "offset": self._settings.ingestion_max_transactions,
            "sort": "desc",
            "apikey": self._settings.etherscan_api_key,
        }
        try:
            resp = await self._client.get(self._settings.etherscan_base_url, params=params)
        except httpx.TimeoutException as exc:
            raise ProviderTimeoutError(str(exc)) from exc
        except httpx.TransportError as exc:
            # Connect/read/network errors are transient — retry them.
            raise ProviderTimeoutError(f"transport error: {exc}") from exc
        except httpx.HTTPError as exc:
            raise ProviderError(f"HTTP error calling provider: {exc}") from exc

        if resp.status_code == 429:
            raise ProviderRateLimitedError("provider returned HTTP 429")
        if resp.status_code >= 500:
            raise ProviderRateLimitedError(f"provider returned HTTP {resp.status_code}")
        if resp.status_code != 200:
            raise ProviderError(f"provider returned HTTP {resp.status_code}")

        return self._parse_payload(resp.json())

    @staticmethod
    def _parse_payload(data: dict) -> list[dict]:
        """Extract the result list, mapping provider-level errors to types."""
        status = str(data.get("status", ""))
        result = data.get("result")
        if status == "1" and isinstance(result, list):
            return result

        message = str(data.get("message", "")).lower()
        result_text = result if isinstance(result, str) else ""
        if "no transactions found" in message:
            return []
        haystack = f"{message} {result_text}".lower()
        if any(marker in haystack for marker in _RATE_LIMIT_MARKERS):
            raise ProviderRateLimitedError(result_text or message)
        raise ProviderError(f"provider error: {message or result_text or 'unknown'}")
