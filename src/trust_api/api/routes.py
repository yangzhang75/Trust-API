"""API routes.

POST /verify runs the full pipeline end-to-end (ingestion -> features ->
scoring -> proof). In Week 1 every stage is a deterministic stub keyed on
the wallet hash, so responses are stable for the same input.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from trust_api.api.deps import get_settings, rate_limit
from trust_api.config import Settings
from trust_api.schemas.verify import (
    ErrorResponse,
    VerifyRequest,
    VerifyResponse,
    is_valid_evm_wallet,
)
from trust_api.services import features, ingestion, proof, scoring

router = APIRouter()


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
) -> VerifyResponse:
    """Run the (stubbed) trust pipeline and return a deterministic result."""
    if not is_valid_evm_wallet(body.wallet):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid wallet address; expected an EVM address (^0x[a-fA-F0-9]{40}$).",
        )

    # Pipeline: ingestion -> features -> scoring -> proof.
    activity = ingestion.fetch_activity(body.wallet, body.chains)
    feats = features.compute_features(activity)
    assessment = scoring.score(feats)
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
