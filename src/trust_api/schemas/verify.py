"""Pydantic v2 models and enums for the /verify API contract.

Wallet format is validated explicitly in the route (not via a Pydantic
pattern) so an invalid wallet returns 400 while a malformed body returns
the framework's default 422.
"""

from __future__ import annotations

import re
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

# EVM address: 0x followed by 40 hex chars. Solana support arrives in Week 2.
EVM_WALLET_REGEX = re.compile(r"^0x[a-fA-F0-9]{40}$")


def is_valid_evm_wallet(wallet: str) -> bool:
    """Return True if ``wallet`` is a syntactically valid EVM address."""
    return bool(EVM_WALLET_REGEX.match(wallet))


class Chain(StrEnum):
    """Supported chains. Solana (and other non-EVM chains) land in Week 2."""

    ethereum = "ethereum"


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


class VerifyRequest(BaseModel):
    """Request body for POST /verify."""

    model_config = ConfigDict(extra="forbid")

    wallet: str = Field(..., examples=["0x52908400098527886E0F7030069857D2E4169EE7"])
    chains: list[Chain] = Field(default_factory=lambda: [Chain.ethereum], min_length=1)


class Proof(BaseModel):
    """A time-bounded, signed attestation of an assessment.

    Week 1 signatures are deterministic stubs and MUST NOT be trusted as
    cryptographic proofs.
    """

    issued_at: datetime
    expires_at: datetime
    valid_for_hours: int = Field(..., ge=1)
    signature: str


class VerifyResponse(BaseModel):
    """200 response body for POST /verify."""

    wallet: str
    human_likelihood: HumanLikelihood
    trust_tier: TrustTier
    confidence_score: float = Field(..., ge=0.0, le=1.0)
    risk_flags: list[RiskFlag]
    chains: list[Chain]
    proof: Proof


class ErrorResponse(BaseModel):
    """Uniform error envelope for documented 4xx responses."""

    detail: str
