"""Proof subsystem — real Ed25519-signed trust proofs (Week 6)."""

from __future__ import annotations

from trust_api.services.proof.keys import Signer, load_signer, verify_signature
from trust_api.services.proof.models import Proof, VerificationResult
from trust_api.services.proof.offline import key_id_for, verify_offline
from trust_api.services.proof.service import ProofService

__all__ = [
    "Proof",
    "ProofService",
    "Signer",
    "VerificationResult",
    "key_id_for",
    "load_signer",
    "verify_offline",
    "verify_signature",
]
