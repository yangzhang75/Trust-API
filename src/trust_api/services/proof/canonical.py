"""Canonical serialization for signed proof payloads.

The signature is computed over a canonical byte form of the payload so that
a verifier can reconstruct exactly the same bytes: sorted keys, no
whitespace, UTF-8. This is the single source of truth for what gets signed.

Caveat (documented in docs/proof.md): floats are serialized with Python's
`json` number formatting. `confidence_score` is rounded to 4 decimals
upstream, which is stable here; a cross-language verifier must reproduce
the same number formatting (a known canonical-JSON concern).
"""

from __future__ import annotations

import json

# The exact field set that is signed, in no particular order (canonicalized).
PAYLOAD_FIELDS = (
    "wallet",
    "human_likelihood",
    "trust_tier",
    "confidence_score",
    "risk_flags",
    "chains",
    "scorer_version",
    "key_id",
    "issued_at",
    "expires_at",
    "nonce",
)


def canonical_bytes(payload: dict) -> bytes:
    """Deterministic bytes for signing/verifying: sorted keys, no whitespace."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )


def build_payload(
    *,
    wallet: str,
    human_likelihood: str,
    trust_tier: str,
    confidence_score: float,
    risk_flags: list[str],
    chains: list[str],
    scorer_version: str,
    key_id: str,
    issued_at: str,
    expires_at: str,
    nonce: str,
) -> dict:
    """Assemble the exact dict that gets canonicalized and signed."""
    return {
        "wallet": wallet,
        "human_likelihood": human_likelihood,
        "trust_tier": trust_tier,
        "confidence_score": confidence_score,
        "risk_flags": list(risk_flags),
        "chains": list(chains),
        "scorer_version": scorer_version,
        "key_id": key_id,
        "issued_at": issued_at,
        "expires_at": expires_at,
        "nonce": nonce,
    }
