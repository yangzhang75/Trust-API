"""API routes.

POST /verify runs the real pipeline: resolve the wallet's behavioral
features (ingesting + computing them on demand when a provider is
configured), score them with the transparent rule engine, and return the
assessment. Proof signing is still stubbed (Week 6).
"""

from __future__ import annotations

import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from trust_api.api.deps import get_settings, rate_limit
from trust_api.config import Settings
from trust_api.core.logging import get_logger
from trust_api.db.models import Wallet, WalletFeature
from trust_api.db.session import get_db
from trust_api.schemas.verify import (
    Chain,
    ErrorResponse,
    VerifyRequest,
    VerifyResponse,
    is_valid_evm_wallet,
)
from trust_api.services import proof
from trust_api.services.features import WalletFeatures, compute_features
from trust_api.services.ingestion import IngestionError, ingest_wallet
from trust_api.services.scoring import score

router = APIRouter()
logger = get_logger(__name__)

# Neutral, all-zero features used when a wallet has no data (and none can be
# fetched). Scored deterministically -> low trust with the expected flags.
_EMPTY_FEATURES = WalletFeatures(
    wallet_id=0,
    chain=Chain.ethereum.value,
    wallet_age_days=0,
    tx_count=0,
    active_days=0,
    tx_per_active_day=0.0,
    counterparty_count=0,
    counterparty_diversity_ratio=0.0,
    inbound_ratio=0.0,
    burst_score=0,
    dormancy_flag=False,
    recency_days=0,
)


def _query_features(db: Session, wallet_address: str) -> WalletFeature | None:
    return db.execute(
        select(WalletFeature).join(Wallet).where(Wallet.address == wallet_address)
    ).scalar_one_or_none()


def _resolve_features(
    db: Session | None, wallet: str, settings: Settings
) -> WalletFeature | WalletFeatures | None:
    """Return the wallet's features, ingesting + computing them on a miss.

    Stub-safe: with no DB, no provider, or any error, returns None so
    /verify falls back to neutral features rather than failing.
    """
    if db is None:
        return None
    try:
        row = _query_features(db, wallet)
        if row is not None:
            return row
        if not settings.ingestion_provider_configured:
            return None
        # Miss + provider available: ingest on demand, compute, re-read.
        result = asyncio.run(ingest_wallet(db, wallet, settings=settings))
        compute_features(db, result.wallet_id)
        return _query_features(db, wallet)
    except (SQLAlchemyError, IngestionError):
        return None


@router.post(
    "/verify",
    response_model=VerifyResponse,
    tags=["verify"],
    summary="Assess the human-likelihood and trust tier of a wallet",
    dependencies=[Depends(rate_limit)],  # requires a valid API key, then rate-limits
    responses={
        400: {"model": ErrorResponse, "description": "Invalid wallet address"},
        401: {"model": ErrorResponse, "description": "Missing or invalid API key"},
        422: {"description": "Malformed request body"},
        429: {"model": ErrorResponse, "description": "Rate limit exceeded"},
    },
)
def verify(
    body: VerifyRequest,
    settings: Annotated[Settings, Depends(get_settings)],
    db: Annotated[Session | None, Depends(get_db)] = None,
) -> VerifyResponse:
    """Resolve features, score them with the rule engine, and return the result."""
    if not is_valid_evm_wallet(body.wallet):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid wallet address; expected an EVM address (^0x[a-fA-F0-9]{40}$).",
        )

    features = _resolve_features(db, body.wallet, settings) or _EMPTY_FEATURES
    result = score(features)
    issued = proof.issue_proof(body.wallet, result, valid_for_hours=settings.proof_valid_for_hours)

    return VerifyResponse(
        wallet=body.wallet,
        human_likelihood=result.human_likelihood,
        trust_tier=result.trust_tier,
        confidence_score=result.confidence_score,
        risk_flags=result.risk_flags,
        chains=body.chains,
        proof=issued,
    )
