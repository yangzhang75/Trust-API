"""Shareable serialization for proofs (Week 9 — Proof Verification Flow).

Two interchangeable wire forms of a self-contained proof (the Week-6 ``Proof``
DTO = ``{payload, signature}``):

  * **raw JSON** — for developer integrations;
  * **compact base64url** of the canonical JSON — fits in a URL or QR code.

Round-trip is deterministic: both forms serialize the *canonical* JSON
(sorted keys, no whitespace, UTF-8), so ``encode`` → ``decode`` → ``encode``
reproduces byte-identical output. No cryptography here — this only (de)serializes
the existing Proof DTO; signing/verification stays in ``ProofService``.
"""

from __future__ import annotations

import base64
import binascii
import json

from trust_api.services.proof.canonical import canonical_bytes
from trust_api.services.proof.models import Proof


def _shared_obj(proof: Proof) -> dict:
    """The self-contained wire object: the signed payload + its signature."""
    return {"payload": proof.payload, "signature": proof.signature}


def proof_to_json(proof: Proof) -> str:
    """Canonical raw-JSON form (sorted keys, no whitespace)."""
    return canonical_bytes(_shared_obj(proof)).decode("utf-8")


def encode_proof(proof: Proof) -> str:
    """Compact base64url form (URL / QR friendly), padding stripped."""
    raw = canonical_bytes(_shared_obj(proof))
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _proof_from_obj(obj: object) -> Proof:
    if not isinstance(obj, dict) or "payload" not in obj or "signature" not in obj:
        raise ValueError("shared proof must be an object with 'payload' and 'signature'")
    payload = obj["payload"]
    signature = obj["signature"]
    if not isinstance(payload, dict) or not isinstance(signature, str):
        raise ValueError("shared proof 'payload' must be an object and 'signature' a string")
    return Proof(payload=payload, signature=signature)


def decode_proof(data: str) -> Proof:
    """Parse EITHER wire form back into a Proof.

    Accepts the raw JSON object or the compact base64url string, so a verifier
    can consume whatever a sharer hands them. Raises ``ValueError`` on anything
    that is neither valid JSON nor valid base64url-of-JSON.
    """
    s = data.strip()
    if s.startswith("{"):
        return _proof_from_obj(json.loads(s))
    padded = s + "=" * (-len(s) % 4)
    try:
        raw = base64.urlsafe_b64decode(padded.encode("ascii"))
        obj = json.loads(raw.decode("utf-8"))
    except (binascii.Error, ValueError) as exc:  # ValueError covers JSON + UTF-8 errors
        raise ValueError("not valid base64url or JSON") from exc
    return _proof_from_obj(obj)


def summarize_payload(payload: dict) -> str:
    """One-line, human-readable summary of a proof's assessment (for display)."""
    return (
        f"{payload.get('wallet', '?')}: "
        f"{payload.get('human_likelihood', '?')} human-likelihood, "
        f"{payload.get('trust_tier', '?')} tier, "
        f"confidence {payload.get('confidence_score', '?')} "
        f"(scorer {payload.get('scorer_version', '?')}, expires {payload.get('expires_at', '?')})"
    )
