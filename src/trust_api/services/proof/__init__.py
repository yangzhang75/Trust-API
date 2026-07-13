"""Proof subsystem.

Week 6 adds real Ed25519 signing (keys.py). The Week-1 stub issue_proof is
kept in legacy.py until /verify is wired to the real ProofService.
"""

from __future__ import annotations

from trust_api.services.proof.keys import Signer, load_signer, verify_signature
from trust_api.services.proof.legacy import issue_proof

__all__ = ["Signer", "issue_proof", "load_signer", "verify_signature"]
