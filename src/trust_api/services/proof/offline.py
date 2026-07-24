"""Offline proof verification — public key only, no server, no DB (Week 9).

A third party who has fetched the issuer's public key (GET /proof/public-key)
validates a proof entirely locally: derive/confirm the key id, check the
Ed25519 signature over the canonical payload, and check the expiry. This is
the recommended, privacy-neutral integration path (see docs/proof-flow.md).

It reuses the exact Week-6 primitives (``verify_signature`` + ``canonical_bytes``)
— no new crypto. ``ProofService.verify`` delegates here for the signature/expiry
checks and only adds revocation, so the server and the offline path run the
same verification. Revocation is the one thing offline verification cannot see
(it lives in the issuer's database).
"""

from __future__ import annotations

import base64
import binascii
import hashlib
from datetime import UTC, datetime

from trust_api.services.proof.canonical import canonical_bytes
from trust_api.services.proof.keys import verify_signature
from trust_api.services.proof.models import Proof, VerificationResult


def key_id_for(public_key_b64: str) -> str:
    """Short, stable key id derived from a base64 public key (matches Signer)."""
    return hashlib.sha256(base64.b64decode(public_key_b64)).hexdigest()[:16]


def verify_offline(
    public_key_b64: str, proof: Proof, *, now: datetime | None = None
) -> VerificationResult:
    """Verify a proof with only the issuer's public key. No network, no DB.

    Order (revocation aside, which needs the issuer's DB):
    ``unknown_key`` -> ``bad_signature`` -> ``expired`` -> ``ok``.
    """
    now = now or datetime.now(UTC)
    key_id = proof.payload.get("key_id")
    if key_id != key_id_for(public_key_b64):
        return VerificationResult(valid=False, reason="unknown_key", key_id=key_id)

    try:
        signature = base64.b64decode(proof.signature, validate=True)
    except (binascii.Error, ValueError):
        return VerificationResult(valid=False, reason="bad_signature", key_id=key_id)
    public_bytes = base64.b64decode(public_key_b64)
    if not verify_signature(public_bytes, canonical_bytes(proof.payload), signature):
        return VerificationResult(valid=False, reason="bad_signature", key_id=key_id)

    if now > datetime.fromisoformat(proof.payload["expires_at"]):
        return VerificationResult(valid=False, reason="expired", key_id=key_id)

    return VerificationResult(valid=True, reason="ok", key_id=key_id)
