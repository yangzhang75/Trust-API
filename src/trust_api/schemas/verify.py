"""Pydantic v2 models and enums for the /verify API contract.

Wallet format is validated explicitly in the route (not via a Pydantic
pattern) so an invalid wallet returns 400 while a malformed body returns
the framework's default 422.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

# The wallet-format validator lives in core.validation (the single source of
# truth shared by /verify and every scoring/ingestion entry point). Re-exported
# here so existing importers of the API schema keep working.
from trust_api.core.validation import (
    is_valid_evm_wallet as is_valid_evm_wallet,
)


class Chain(StrEnum):
    """Supported EVM chains (Etherscan V2 via chainid). Non-EVM chains later."""

    ethereum = "ethereum"
    arbitrum = "arbitrum"


class HumanLikelihood(StrEnum):
    """Qualitative likelihood that the wallet is operated by a real human."""

    high = "high"
    medium = "medium"
    low = "low"


class TrustTier(StrEnum):
    """Coarse reputation tier assigned to a wallet."""

    bronze = "bronze"
    silver = "silver"
    gold = "gold"


class RiskFlag(StrEnum):
    """Risk signals attached to an assessment (Week 4: emitted by real rules)."""

    new_wallet = "new_wallet"
    low_activity = "low_activity"
    low_counterparty_diversity = "low_counterparty_diversity"
    bot_burst = "bot_burst"
    dormant = "dormant"
    sybil_suspected = "sybil_suspected"
    sybil_cluster = "sybil_cluster"


class VerifyRequest(BaseModel):
    """Request body for POST /verify."""

    model_config = ConfigDict(extra="forbid")

    wallet: str = Field(..., examples=["0x52908400098527886E0F7030069857D2E4169EE7"])
    chains: list[Chain] = Field(default_factory=lambda: [Chain.ethereum], min_length=1)


class Proof(BaseModel):
    """A time-bounded, Ed25519-signed attestation of an assessment.

    ``issued_at`` / ``expires_at`` are the EXACT ISO-8601 strings that were
    signed (verbatim, not re-serialized), so a verifier can reconstruct the
    byte-identical canonical payload. See docs/proof.md.
    """

    issued_at: str
    expires_at: str
    valid_for_hours: int = Field(..., ge=1)
    signature: str  # base64 Ed25519 signature over the canonical payload
    key_id: str
    nonce: str
    scorer_version: str


class VerifyResponse(BaseModel):
    """200 response body for POST /verify."""

    wallet: str
    human_likelihood: HumanLikelihood
    trust_tier: TrustTier
    confidence_score: float = Field(..., ge=0.0, le=1.0)
    risk_flags: list[RiskFlag]
    chains: list[Chain]
    proof: Proof


class ProofVerifyRequest(VerifyResponse):
    """Request body for POST /proof/verify.

    Deliberately the same shape as a VerifyResponse: a consumer submits back
    exactly what /verify returned and we recheck it. Every signed field is
    required to reconstruct the canonical payload the signature covers.
    """


class GeneratedProof(BaseModel):
    """200 response body for POST /proof/generate.

    A self-contained, shareable proof. ``payload`` is the exact canonical
    object the signature covers (the 11 signed fields); ``signature`` is the
    base64 Ed25519 signature; ``encoded`` is the compact base64url form of
    ``{payload, signature}`` (URL / QR friendly); ``summary`` is a one-line
    human-readable description for display. A verifier needs nothing else and
    no server callback — see docs/proof-flow.md.
    """

    payload: dict
    signature: str
    encoded: str
    summary: str


class ProofVerifyResponse(BaseModel):
    """200 response body for POST /proof/verify."""

    valid: bool
    # One of: ok, unknown_key, bad_signature, revoked, expired.
    reason: str
    key_id: str | None = None


class ErrorResponse(BaseModel):
    """Uniform error envelope for documented 4xx responses."""

    detail: str
