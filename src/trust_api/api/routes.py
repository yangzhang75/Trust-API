"""API routes.

POST /verify runs the full pipeline end-to-end (ingestion -> features ->
scoring -> proof). In Week 1 every stage is a deterministic stub keyed on
the wallet hash, so responses are stable for the same input.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from trust_api.api.deps import get_settings, rate_limit
from trust_api.config import Settings
from trust_api.db.models import Wallet, WalletFeature
from trust_api.db.session import get_db
from trust_api.schemas.verify import (
    ErrorResponse,
    VerifyRequest,
    VerifyResponse,
    is_valid_evm_wallet,
)
from trust_api.services import features, ingestion, proof, scoring

router = APIRouter()


def _stored_features(db: Session | None, wallet_address: str) -> WalletFeature | None:
    """Return the wallet's computed features if present; None otherwise.

    Stub-safe: any DB unavailability degrades to None so /verify never
    fails because features haven't been computed (or there's no database).
    """
    if db is None:
        return None
    try:
        return db.execute(
            select(WalletFeature).join(Wallet).where(Wallet.address == wallet_address)
        ).scalar_one_or_none()
    except SQLAlchemyError:
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
    """Run the (stubbed) trust pipeline and return a deterministic result."""
    if not is_valid_evm_wallet(body.wallet):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid wallet address; expected an EVM address (^0x[a-fA-F0-9]{40}$).",
        )

    # Pipeline: ingestion -> features -> scoring -> proof.
    # Week 3: if this wallet has been ingested, wire its real features into
    # scoring — the output is still a deterministic stub (real scoring: Week 4).
    activity = ingestion.fetch_activity(body.wallet, body.chains)
    feats = features.compute_activity_features(activity)
    stored = _stored_features(db, body.wallet)
    assessment = scoring.score(feats, stored_features=stored)
    issued = proof.issue_proof(
        body.wallet, assessment, valid_for_hours=settings.proof_valid_for_hours
    )

    return VerifyResponse(
        wallet=body.wallet,
        human_likelihood=assessment.human_likelihood,
        trust_tier=assessment.trust_tier,
        confidence_score=assessment.confidence_score,
        risk_flags=assessment.risk_flags,
        chains=body.chains,
        proof=issued,
    )
