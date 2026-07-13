"""Proof subsystem — real Ed25519-signed trust proofs (Week 6)."""

from __future__ import annotations

from trust_api.services.proof.keys import Signer, load_signer, verify_signature
from trust_api.services.proof.models import Proof, VerificationResult
from trust_api.services.proof.service import ProofService

__all__ = [
    "Proof",
    "ProofService",
    "Signer",
    "VerificationResult",
    "load_signer",
    "verify_signature",
]
