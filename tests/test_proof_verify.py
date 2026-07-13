"""Tests for ProofService.verify — every reason branch."""

from __future__ import annotations

import base64
from datetime import UTC, datetime, timedelta

from sqlalchemy import update
from sqlalchemy.orm import Session

from trust_api.config import Settings
from trust_api.db.models import Proof as ProofRow
from trust_api.schemas.verify import HumanLikelihood, TrustTier
from trust_api.services.proof import ProofService, load_signer
from trust_api.services.proof.models import Proof
from trust_api.services.scoring import ScoringResult

KEY_A = base64.b64encode(b"a" * 32).decode()
KEY_B = base64.b64encode(b"b" * 32).decode()
WALLET = "0x52908400098527886E0F7030069857D2E4169EE7"
NOW = datetime(2026, 1, 1, tzinfo=UTC)
RESULT = ScoringResult(HumanLikelihood.high, TrustTier.gold, 0.9, [])


def _svc(key: str = KEY_A) -> ProofService:
    return ProofService(load_signer(Settings(proof_signing_key=key)), ttl_hours=24)


def test_round_trip_valid() -> None:
    svc = _svc()
    proof = svc.generate(wallet=WALLET, result=RESULT, chains=["ethereum"], now=NOW)
    r = svc.verify(proof, now=NOW)
    assert r.valid is True and r.reason == "ok"


def test_tampered_payload_is_bad_signature() -> None:
    svc = _svc()
    proof = svc.generate(wallet=WALLET, result=RESULT, chains=["ethereum"], now=NOW)
    tampered = Proof(payload={**proof.payload, "trust_tier": "bronze"}, signature=proof.signature)
    assert svc.verify(tampered, now=NOW).reason == "bad_signature"


def test_malformed_signature_is_bad_signature() -> None:
    svc = _svc()
    proof = svc.generate(wallet=WALLET, result=RESULT, chains=["ethereum"], now=NOW)
    bad = Proof(payload=proof.payload, signature="not base64 !!!")
    assert svc.verify(bad, now=NOW).reason == "bad_signature"


def test_expired_proof() -> None:
    svc = _svc()
    proof = svc.generate(wallet=WALLET, result=RESULT, chains=["ethereum"], now=NOW)
    r = svc.verify(proof, now=NOW + timedelta(hours=25))
    assert r.valid is False and r.reason == "expired"


def test_unknown_key() -> None:
    proof = _svc(KEY_B).generate(wallet=WALLET, result=RESULT, chains=["ethereum"], now=NOW)
    r = _svc(KEY_A).verify(proof, now=NOW)  # verifier only knows key A
    assert r.valid is False and r.reason == "unknown_key"


def test_canonicalization_is_order_independent() -> None:
    svc = _svc()
    proof = svc.generate(wallet=WALLET, result=RESULT, chains=["ethereum"], now=NOW)
    reordered = Proof(
        payload=dict(reversed(list(proof.payload.items()))), signature=proof.signature
    )
    assert svc.verify(reordered, now=NOW).valid is True  # key order doesn't matter


def test_revoked_proof(db_session: Session) -> None:
    svc = _svc()
    proof = svc.generate(
        wallet=WALLET, result=RESULT, chains=["ethereum"], session=db_session, now=NOW
    )
    assert svc.verify(proof, session=db_session, now=NOW).reason == "ok"
    db_session.execute(update(ProofRow).values(revoked=True))
    db_session.commit()
    r = svc.verify(proof, session=db_session, now=NOW)
    assert r.valid is False and r.reason == "revoked"
