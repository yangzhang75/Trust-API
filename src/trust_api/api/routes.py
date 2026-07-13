"""API routes.

POST /verify runs the real pipeline: resolve the wallet's behavioral
features (ingesting + computing them on demand when a provider is
configured), score them with the transparent rule engine, and return the
assessment together with a real Ed25519-signed, expiring proof.
"""

from __future__ import annotations

import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from trust_api.api.deps import get_settings, get_signer, rate_limit
from trust_api.config import Settings
from trust_api.core.logging import get_logger
from trust_api.db.models import Wallet, WalletFeature
from trust_api.db.session import get_db
from trust_api.schemas.verify import (
    ErrorResponse,
    Proof,
    ProofVerifyRequest,
    ProofVerifyResponse,
    VerifyRequest,
    VerifyResponse,
    is_valid_evm_wallet,
)
from trust_api.services.features import EMPTY_FEATURES, WalletFeatures, compute_features
from trust_api.services.ingestion import IngestionError, ingest_wallet
from trust_api.services.proof import ProofService, Signer
from trust_api.services.proof.canonical import build_payload
from trust_api.services.proof.models import Proof as ProofDTO
from trust_api.services.scoring import score

router = APIRouter()
logger = get_logger(__name__)


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
    signer: Annotated[Signer, Depends(get_signer)],
    db: Annotated[Session | None, Depends(get_db)] = None,
) -> VerifyResponse:
    """Resolve features, score them, and return a signed proof."""
    if not is_valid_evm_wallet(body.wallet):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid wallet address; expected an EVM address (^0x[a-fA-F0-9]{40}$).",
        )

    features = _resolve_features(db, body.wallet, settings) or EMPTY_FEATURES
    result = score(features)
    signed = ProofService(signer, settings.proof_ttl_hours).generate(
        wallet=body.wallet,
        result=result,
        chains=[c.value for c in body.chains],
        session=db,
    )

    return VerifyResponse(
        wallet=body.wallet,
        human_likelihood=result.human_likelihood,
        trust_tier=result.trust_tier,
        confidence_score=result.confidence_score,
        risk_flags=result.risk_flags,
        chains=body.chains,
        proof=Proof(
            issued_at=signed.issued_at,
            expires_at=signed.expires_at,
            valid_for_hours=settings.proof_ttl_hours,
            signature=signed.signature,
            key_id=signed.key_id,
            nonce=signed.nonce,
            scorer_version=signed.payload["scorer_version"],
        ),
    )


@router.post(
    "/proof/verify",
    response_model=ProofVerifyResponse,
    tags=["proof"],
    summary="Verify a previously issued proof",
    dependencies=[Depends(rate_limit)],  # requires a valid API key, then rate-limits
    responses={
        401: {"model": ErrorResponse, "description": "Missing or invalid API key"},
        422: {"description": "Malformed request body"},
        429: {"model": ErrorResponse, "description": "Rate limit exceeded"},
    },
)
def verify_proof(
    body: ProofVerifyRequest,
    settings: Annotated[Settings, Depends(get_settings)],
    signer: Annotated[Signer, Depends(get_signer)],
    db: Annotated[Session | None, Depends(get_db)] = None,
) -> ProofVerifyResponse:
    """Recheck a submitted proof: reconstruct the canonical payload, verify the
    signature/expiry with our key, and consult the DB for revocation.

    This is a convenience endpoint; the same check runs offline with only the
    public key (see docs/proof.md). Revocation is only consulted when a DB is
    available.
    """
    payload = build_payload(
        wallet=body.wallet,
        human_likelihood=body.human_likelihood.value,
        trust_tier=body.trust_tier.value,
        confidence_score=body.confidence_score,
        risk_flags=[f.value for f in body.risk_flags],
        chains=[c.value for c in body.chains],
        scorer_version=body.proof.scorer_version,
        key_id=body.proof.key_id,
        issued_at=body.proof.issued_at,
        expires_at=body.proof.expires_at,
        nonce=body.proof.nonce,
    )
    proof = ProofDTO(payload=payload, signature=body.proof.signature)
    result = ProofService(signer, settings.proof_ttl_hours).verify(proof, session=db)
    return ProofVerifyResponse(valid=result.valid, reason=result.reason, key_id=result.key_id)
