"""Tests for canonical proof serialization."""

from __future__ import annotations

from trust_api.services.proof.canonical import build_payload, canonical_bytes
from trust_api.services.proof.models import Proof, VerificationResult


def test_proof_dto_accessors() -> None:
    payload = {
        "key_id": "kid",
        "issued_at": "t0",
        "expires_at": "t1",
        "nonce": "n",
        "wallet": "0x",
    }
    proof = Proof(payload=payload, signature="sig")
    assert proof.key_id == "kid"
    assert proof.issued_at == "t0"
    assert proof.expires_at == "t1"
    assert proof.nonce == "n"


def test_verification_result_defaults() -> None:
    r = VerificationResult(valid=True, reason="ok", key_id="kid")
    assert (r.valid, r.reason, r.key_id) == (True, "ok", "kid")
    assert VerificationResult(valid=False, reason="expired").key_id is None


def test_canonical_is_key_order_independent() -> None:
    a = canonical_bytes({"b": 1, "a": 2, "c": [3, 2, 1]})
    b = canonical_bytes({"c": [3, 2, 1], "a": 2, "b": 1})
    assert a == b  # sorted keys -> identical bytes regardless of input order


def test_canonical_has_no_whitespace_and_sorted_keys() -> None:
    assert canonical_bytes({"b": 1, "a": 2}) == b'{"a":2,"b":1}'


def test_build_payload_has_exact_fields() -> None:
    payload = build_payload(
        wallet="0xabc",
        human_likelihood="high",
        trust_tier="gold",
        confidence_score=0.8375,
        risk_flags=["dormant"],
        chains=["ethereum"],
        scorer_version="0.4.0-graph",
        key_id="deadbeef",
        issued_at="2026-01-01T00:00:00+00:00",
        expires_at="2026-01-02T00:00:00+00:00",
        nonce="ab12",
    )
    from trust_api.services.proof.canonical import PAYLOAD_FIELDS

    assert set(payload) == set(PAYLOAD_FIELDS)
    assert payload["confidence_score"] == 0.8375
    # canonical bytes are reproducible
    assert canonical_bytes(payload) == canonical_bytes(dict(reversed(list(payload.items()))))
