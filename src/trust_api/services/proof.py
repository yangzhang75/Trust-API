"""Proof service — issues a time-bounded attestation of an assessment.

Week 1 is a STUB: the "signature" is a deterministic hash, NOT a real
cryptographic signature. Do not rely on it for verification.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta

from trust_api.schemas.verify import Proof
from trust_api.services.scoring import TrustAssessment


def _stub_signature(wallet: str, assessment: TrustAssessment, issued_at: datetime) -> str:
    """Deterministic placeholder signature over the assessment payload."""
    payload = "|".join(
        [
            wallet.lower(),
            assessment.human_likelihood.value,
            assessment.trust_tier.value,
            f"{assessment.confidence_score:.4f}",
            issued_at.isoformat(),
        ]
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return f"stub-{digest[:32]}"


def issue_proof(
    wallet: str,
    assessment: TrustAssessment,
    valid_for_hours: int,
    *,
    now: datetime | None = None,
) -> Proof:
    """Issue a Proof for ``assessment``.

    TODO(week5): replace the stub signature with real signing (e.g. an
    Ed25519/secp256k1 key in a KMS/HSM) and persist the issued proof
    (jsonb payload only — never raw tx data) to the proofs table.
    """
    issued_at = now or datetime.now(UTC)
    expires_at = issued_at + timedelta(hours=valid_for_hours)
    return Proof(
        issued_at=issued_at,
        expires_at=expires_at,
        valid_for_hours=valid_for_hours,
        signature=_stub_signature(wallet, assessment, issued_at),
    )
