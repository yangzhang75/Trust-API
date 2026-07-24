"""API routes.

POST /verify runs the real pipeline: resolve the wallet's behavioral
features (ingesting + computing them on demand when a provider is
configured), score them with the transparent rule engine, and return the
assessment together with a real Ed25519-signed, expiring proof.
"""

from __future__ import annotations

import asyncio
from time import perf_counter
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from trust_api.api.deps import get_settings, get_signer, rate_limit
from trust_api.config import Settings
from trust_api.core.logging import get_logger
from trust_api.core.metrics import METRICS
from trust_api.db.models import Wallet, WalletFeature
from trust_api.db.session import get_db
from trust_api.pipeline import INGEST_CHAINS, record_score
from trust_api.schemas.verify import (
    ErrorResponse,
    GeneratedProof,
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
from trust_api.services.proof.models import Proof as ProofDTO
from trust_api.services.proof.share import decode_proof, encode_proof, summarize_payload
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
        # Miss + provider available: ingest on demand (both chains, like the
        # pipeline), compute features, re-read. This is why a first /verify of
        # a real wallet (e.g. vitalik) scores on real activity, not empties.
        wallet_id = 0
        for chain in INGEST_CHAINS:
            wallet_id = asyncio.run(ingest_wallet(db, wallet, chain, settings=settings)).wallet_id
        compute_features(db, wallet_id)
        return _query_features(db, wallet)
    except (SQLAlchemyError, IngestionError):
        return None


def _record_score_history(db: Session | None, wallet: str, result) -> None:
    """Append this /verify to trust_score_history so the dashboard's scored-
    wallet count and score distribution reflect real traffic. Best-effort:
    a DB failure is logged and swallowed — it must never break /verify.
    """
    if db is None:
        return
    try:
        record_score(db, wallet, result)
    except SQLAlchemyError:
        db.rollback()
        logger.warning("verify: score-history persist failed (wallet=%s)", wallet)


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

    started = perf_counter()
    features = _resolve_features(db, body.wallet, settings) or EMPTY_FEATURES
    result = score(features)
    # Bump the SAME shared-Redis counters the pipeline uses, so System health's
    # scoring metrics (and avg duration) reflect /verify traffic too — not just
    # the worker. Best-effort inside METRICS (Redis outage is swallowed).
    METRICS.record(ok=True, duration_seconds=perf_counter() - started)

    signed = ProofService(signer, settings.proof_ttl_hours).generate(
        wallet=body.wallet,
        result=result,
        chains=[c.value for c in body.chains],
        session=db,
    )
    _record_score_history(db, body.wallet, result)

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
    "/proof/generate",
    response_model=GeneratedProof,
    tags=["proof"],
    summary="Generate a self-contained, shareable trust proof for a wallet",
    dependencies=[Depends(rate_limit)],  # requires a valid API key, then rate-limits
    responses={
        400: {"model": ErrorResponse, "description": "Invalid wallet address"},
        401: {"model": ErrorResponse, "description": "Missing or invalid API key"},
        422: {"description": "Malformed request body"},
        429: {"model": ErrorResponse, "description": "Rate limit exceeded"},
    },
)
def generate_proof(
    body: VerifyRequest,
    settings: Annotated[Settings, Depends(get_settings)],
    signer: Annotated[Signer, Depends(get_signer)],
    db: Annotated[Session | None, Depends(get_db)] = None,
) -> GeneratedProof:
    """Score the wallet (same feature-resolve + rule engine as /verify) and
    return a self-contained proof that can be shared as-is: the canonical
    payload, its signature, a compact base64url form, and a human summary.

    Reuses the Week-6 ProofService verbatim — no new crypto. Persisting the
    proof (when a DB is available) is what makes it later revocable.
    """
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
    return GeneratedProof(
        payload=signed.payload,
        signature=signed.signature,
        encoded=encode_proof(signed),
        summary=summarize_payload(signed.payload),
    )


def _proof_from_request(body: ProofVerifyRequest) -> ProofDTO:
    """Turn a /proof/verify request (encoded OR payload+signature) into a Proof.

    Raises 422 for a request that carries neither complete form or an encoded
    string that isn't valid base64url-of-JSON.
    """
    if body.encoded is not None:
        try:
            return decode_proof(body.encoded)
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail=f"Malformed encoded proof: {exc}",
            ) from exc
    if body.payload is not None and body.signature is not None:
        return ProofDTO(payload=body.payload, signature=body.signature)
    raise HTTPException(
        status_code=422,
        detail="Provide either 'encoded' or both 'payload' and 'signature'.",
    )


@router.post(
    "/proof/verify",
    response_model=ProofVerifyResponse,
    tags=["proof"],
    summary="Verify a self-contained proof (raw JSON or encoded form)",
    dependencies=[Depends(rate_limit)],  # requires a valid API key, then rate-limits
    responses={
        401: {"model": ErrorResponse, "description": "Missing or invalid API key"},
        422: {"description": "Malformed request body / unparseable proof"},
        429: {"model": ErrorResponse, "description": "Rate limit exceeded"},
    },
)
def verify_proof(
    body: ProofVerifyRequest,
    settings: Annotated[Settings, Depends(get_settings)],
    signer: Annotated[Signer, Depends(get_signer)],
    db: Annotated[Session | None, Depends(get_db)] = None,
) -> ProofVerifyResponse:
    """Recheck a self-contained proof, submitted as raw JSON or the compact
    encoded form: verify signature + expiry with our key and consult the DB for
    revocation.

    Auth: this convenience endpoint requires an API key (like the rest of the
    API) — verification has a real cost (a signature check + a DB lookup) and
    leaving it open invites anonymous verification farming / DoS. The genuinely
    public, no-auth, no-server path is OFFLINE verification with our published
    public key; that is the recommended integration route (see docs/proof-flow.md).
    Revocation is only consulted when a DB is available.
    """
    proof = _proof_from_request(body)
    result = ProofService(signer, settings.proof_ttl_hours).verify(proof, session=db)
    return ProofVerifyResponse(
        valid=result.valid,
        reason=result.reason,
        key_id=result.key_id,
        expires_at=proof.payload.get("expires_at"),
        revoked=result.reason == "revoked",
        summary=summarize_payload(proof.payload),
    )
