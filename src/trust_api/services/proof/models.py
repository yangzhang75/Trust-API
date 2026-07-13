"""Proof DTOs."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Proof:
    """A signed proof: the canonical payload plus its base64 signature."""

    payload: dict
    signature: str  # base64

    @property
    def key_id(self) -> str:
        return self.payload["key_id"]

    @property
    def issued_at(self) -> str:
        return self.payload["issued_at"]

    @property
    def expires_at(self) -> str:
        return self.payload["expires_at"]

    @property
    def nonce(self) -> str:
        return self.payload["nonce"]


@dataclass(frozen=True)
class VerificationResult:
    """Outcome of verifying a proof."""

    valid: bool
    reason: str  # "ok" | "expired" | "bad_signature" | "revoked" | "unknown_key"
    key_id: str | None = None
