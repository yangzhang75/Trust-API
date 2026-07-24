"""Tests for offline proof verification (public key only, no server/DB)."""

from __future__ import annotations

import base64
from datetime import UTC, datetime, timedelta

from trust_api.config import Settings
from trust_api.schemas.verify import HumanLikelihood, RiskFlag, TrustTier
from trust_api.services.proof import ProofService, load_signer
from trust_api.services.proof.models import Proof
from trust_api.services.proof.offline import key_id_for, verify_offline
from trust_api.services.scoring import ScoringResult

KEY_B64 = base64.b64encode(b"0" * 32).decode()
OTHER_KEY_B64 = base64.b64encode(b"1" * 32).decode()
WALLET = "0x52908400098527886E0F7030069857D2E4169EE7"
RESULT = ScoringResult(HumanLikelihood.high, TrustTier.gold, 0.8375, [RiskFlag.dormant])


def _signer(key: str = KEY_B64):
    return load_signer(Settings(proof_signing_key=key))


def _proof(signer) -> Proof:
    return ProofService(signer, ttl_hours=24).generate(
        wallet=WALLET, result=RESULT, chains=["ethereum"], nonce="ab"
    )


def test_key_id_for_matches_signer() -> None:
    signer = _signer()
    assert key_id_for(signer.public_key_b64()) == signer.key_id


def test_verify_offline_accepts_valid_proof() -> None:
    signer = _signer()
    result = verify_offline(signer.public_key_b64(), _proof(signer))
    assert result.valid is True
    assert result.reason == "ok"
    assert result.key_id == signer.key_id


def test_verify_offline_rejects_unknown_key() -> None:
    signer = _signer()
    proof = _proof(signer)
    result = verify_offline(_signer(OTHER_KEY_B64).public_key_b64(), proof)
    assert result.valid is False
    assert result.reason == "unknown_key"
    assert result.key_id == signer.key_id  # echoes the proof's claimed key_id


def test_verify_offline_rejects_tampered_payload() -> None:
    signer = _signer()
    proof = _proof(signer)
    # RESULT is gold, so flip to a genuinely different tier.
    tampered = Proof(payload={**proof.payload, "trust_tier": "bronze"}, signature=proof.signature)
    result = verify_offline(signer.public_key_b64(), tampered)
    assert result.reason == "bad_signature"


def test_verify_offline_rejects_non_base64_signature() -> None:
    signer = _signer()
    proof = _proof(signer)
    bad = Proof(payload=proof.payload, signature="!!! not base64 !!!")
    result = verify_offline(signer.public_key_b64(), bad)
    assert result.reason == "bad_signature"


def test_verify_offline_rejects_expired_proof() -> None:
    signer = _signer()
    proof = _proof(signer)
    after_expiry = datetime.fromisoformat(proof.expires_at) + timedelta(seconds=1)
    result = verify_offline(signer.public_key_b64(), proof, now=after_expiry)
    assert result.reason == "expired"


def test_verify_offline_matches_service_for_signature_and_expiry() -> None:
    """The server path (ProofService.verify without a session) and the offline
    path agree — they share one implementation."""
    signer = _signer()
    proof = _proof(signer)
    now = datetime.now(UTC)
    svc = ProofService(signer, ttl_hours=24).verify(proof, now=now)
    off = verify_offline(signer.public_key_b64(), proof, now=now)
    assert (svc.valid, svc.reason, svc.key_id) == (off.valid, off.reason, off.key_id)
