"""Tests for ProofService.generate + persistence."""

from __future__ import annotations

import base64
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from trust_api.config import Settings
from trust_api.db.models import Proof as ProofRow
from trust_api.schemas.verify import HumanLikelihood, RiskFlag, TrustTier
from trust_api.services.proof import ProofService, load_signer, verify_signature
from trust_api.services.proof.canonical import canonical_bytes
from trust_api.services.scoring import SCORER_VERSION, ScoringResult

KEY_B64 = base64.b64encode(b"0" * 32).decode()
WALLET = "0x52908400098527886E0F7030069857D2E4169EE7"
NOW = datetime(2026, 1, 1, tzinfo=UTC)
RESULT = ScoringResult(HumanLikelihood.high, TrustTier.gold, 0.8375, [RiskFlag.dormant])


def _service() -> ProofService:
    return ProofService(load_signer(Settings(proof_signing_key=KEY_B64)), ttl_hours=24)


def test_generate_produces_verifiable_signature() -> None:
    svc = _service()
    signer = load_signer(Settings(proof_signing_key=KEY_B64))
    proof = svc.generate(wallet=WALLET, result=RESULT, chains=["ethereum"], now=NOW, nonce="ab")

    assert proof.key_id == signer.key_id
    assert proof.payload["scorer_version"] == SCORER_VERSION
    assert proof.payload["confidence_score"] == 0.8375
    sig = base64.b64decode(proof.signature)
    assert verify_signature(signer.public_bytes, canonical_bytes(proof.payload), sig) is True


def test_two_proofs_differ_but_both_verify() -> None:
    svc = _service()
    signer = load_signer(Settings(proof_signing_key=KEY_B64))
    p1 = svc.generate(wallet=WALLET, result=RESULT, chains=["ethereum"], now=NOW)
    p2 = svc.generate(wallet=WALLET, result=RESULT, chains=["ethereum"], now=NOW)
    assert p1.signature != p2.signature  # random nonce -> different signatures
    for p in (p1, p2):
        sig = base64.b64decode(p.signature)
        assert verify_signature(signer.public_bytes, canonical_bytes(p.payload), sig)


def test_generate_persists_proof_row(db_session: Session) -> None:
    svc = _service()
    svc.generate(wallet=WALLET, result=RESULT, chains=["ethereum"], session=db_session, now=NOW)
    row = db_session.execute(select(ProofRow)).scalar_one()
    assert row.key_id and row.revoked is False
    assert row.payload["wallet"] == WALLET
    assert row.valid_for_hours == 24


def test_generate_reuses_existing_wallet_row(db_session: Session) -> None:
    from sqlalchemy import func

    from trust_api.db.models import Wallet

    db_session.add(Wallet(address=WALLET))  # wallet already exists
    db_session.commit()
    _service().generate(
        wallet=WALLET, result=RESULT, chains=["ethereum"], session=db_session, now=NOW
    )
    assert db_session.execute(select(func.count(Wallet.id))).scalar_one() == 1  # not duplicated
    assert db_session.execute(select(func.count(ProofRow.id))).scalar_one() == 1
