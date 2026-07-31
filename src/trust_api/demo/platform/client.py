"""Trust API HTTP client — the ONLY channel the mock uses to reach the API.

Everything goes over the public interface (real HTTP, real ``X-API-Key``); the
mock never imports Trust API scoring/proof code. A caller may inject a
pre-built ``httpx.Client`` (used in tests via ``httpx.MockTransport``).
"""

from __future__ import annotations

import httpx


class TrustError(Exception):
    """A Trust API call failed (non-200 response, or the request never landed).

    ``status_code`` is the HTTP status, or 0 when the request itself failed
    (connection refused / timeout).
    """

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(f"Trust API error {status_code}: {detail}")
        self.status_code = status_code
        self.detail = detail


class TrustClient:
    """Thin wrapper over the Trust API's ``/verify`` and ``/proof/generate``."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        client: httpx.Client | None = None,
        timeout: float = 10.0,
    ) -> None:
        self._client = client or httpx.Client(base_url=base_url, timeout=timeout)
        self._headers = {"X-API-Key": api_key}

    def _post(self, path: str, payload: dict) -> dict:
        try:
            resp = self._client.post(path, json=payload, headers=self._headers)
        except httpx.HTTPError as exc:  # connection refused, timeout, DNS, …
            raise TrustError(0, f"request to {path} failed: {exc}") from exc
        if resp.status_code != 200:
            content_type = resp.headers.get("content-type", "")
            detail = resp.json().get("detail", resp.text) if "json" in content_type else resp.text
            raise TrustError(resp.status_code, str(detail))
        return resp.json()

    @staticmethod
    def _payload(wallet: str, chains: list[str] | None) -> dict:
        payload: dict = {"wallet": wallet}
        if chains:
            payload["chains"] = chains
        return payload

    def verify(self, wallet: str, chains: list[str] | None = None) -> dict:
        """POST /verify — returns the assessment (trust_tier, human_likelihood, …)."""
        return self._post("/verify", self._payload(wallet, chains))

    def generate_proof(self, wallet: str, chains: list[str] | None = None) -> dict:
        """POST /proof/generate — returns a self-contained, shareable proof."""
        return self._post("/proof/generate", self._payload(wallet, chains))

    def close(self) -> None:
        self._client.close()
