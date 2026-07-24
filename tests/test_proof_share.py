"""Tests for the shareable proof serialization (trust_api.services.proof.share).

Round-trip determinism and the two interchangeable wire forms (raw JSON /
compact base64url), plus the decoder's error handling. No crypto here — that
lives in ProofService (test_proof_service / test_proof_verify)."""

from __future__ import annotations

import base64
import json

import pytest

from trust_api.config import Settings
from trust_api.schemas.verify import HumanLikelihood, RiskFlag, TrustTier
from trust_api.services.proof import ProofService, load_signer
from trust_api.services.proof.canonical import canonical_bytes
from trust_api.services.proof.models import Proof
from trust_api.services.proof.share import (
    decode_proof,
    encode_proof,
    proof_to_json,
    summarize_payload,
)
from trust_api.services.scoring import ScoringResult

KEY_B64 = base64.b64encode(b"0" * 32).decode()
WALLET = "0x52908400098527886E0F7030069857D2E4169EE7"
RESULT = ScoringResult(HumanLikelihood.high, TrustTier.gold, 0.8375, [RiskFlag.dormant])


def _proof() -> Proof:
    svc = ProofService(load_signer(Settings(proof_signing_key=KEY_B64)), ttl_hours=24)
    return svc.generate(wallet=WALLET, result=RESULT, chains=["ethereum"], nonce="ab")


def test_encode_is_base64url_without_padding() -> None:
    encoded = encode_proof(_proof())
    assert "=" not in encoded  # padding stripped -> URL/QR friendly
    assert set(encoded) <= set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_")


def test_json_form_round_trips_to_identical_proof() -> None:
    proof = _proof()
    decoded = decode_proof(proof_to_json(proof))
    assert decoded.payload == proof.payload
    assert decoded.signature == proof.signature


def test_encoded_form_round_trips_to_identical_proof() -> None:
    proof = _proof()
    decoded = decode_proof(encode_proof(proof))
    assert decoded.payload == proof.payload
    assert decoded.signature == proof.signature


def test_round_trip_is_deterministic_and_byte_stable() -> None:
    """encode -> decode -> encode reproduces byte-identical output, and both
    wire forms carry the same canonical bytes."""
    proof = _proof()
    encoded = encode_proof(proof)
    assert encode_proof(decode_proof(encoded)) == encoded
    # The base64url form decodes to exactly the canonical JSON form's bytes.
    padded = encoded + "=" * (-len(encoded) % 4)
    assert base64.urlsafe_b64decode(padded) == proof_to_json(proof).encode("utf-8")
    assert proof_to_json(proof).encode("utf-8") == canonical_bytes(
        {"payload": proof.payload, "signature": proof.signature}
    )


def test_decode_rejects_non_object_json() -> None:
    # base64url of a JSON array -> decodes cleanly, but isn't a proof object.
    encoded = base64.urlsafe_b64encode(b"[1, 2, 3]").rstrip(b"=").decode("ascii")
    with pytest.raises(ValueError, match="must be an object"):
        decode_proof(encoded)


def test_decode_rejects_object_missing_fields() -> None:
    with pytest.raises(ValueError, match="'payload' and 'signature'"):
        decode_proof('{"payload": {}}')


def test_decode_rejects_wrong_field_types() -> None:
    with pytest.raises(ValueError, match="must be an object and 'signature' a string"):
        decode_proof('{"payload": 1, "signature": "x"}')


def test_decode_rejects_garbage() -> None:
    with pytest.raises(ValueError, match="not valid base64url or JSON"):
        decode_proof("!!! not base64 !!!")


def test_decode_encoded_object_without_leading_brace_whitespace() -> None:
    """A JSON object with leading whitespace is still recognized as JSON."""
    proof = _proof()
    decoded = decode_proof("  " + proof_to_json(proof))
    assert decoded.signature == proof.signature


def test_summarize_payload_is_human_readable() -> None:
    summary = summarize_payload(_proof().payload)
    assert WALLET in summary
    assert "high human-likelihood" in summary
    assert "gold tier" in summary
    assert "confidence 0.8375" in summary


def test_summarize_payload_tolerates_missing_fields() -> None:
    assert summarize_payload({}) == (
        "?: ? human-likelihood, ? tier, confidence ? (scorer ?, expires ?)"
    )


def test_json_form_is_valid_json() -> None:
    obj = json.loads(proof_to_json(_proof()))
    assert set(obj) == {"payload", "signature"}
