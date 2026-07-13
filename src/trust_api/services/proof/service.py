"""ProofService — generate and (Week 6 step 4) verify signed proofs."""

from __future__ import annotations

import base64
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from trust_api.db.models import Proof as ProofRow
from trust_api.db.models import Wallet
from trust_api.services.proof.canonical import build_payload, canonical_bytes
from trust_api.services.proof.keys import Signer
from trust_api.services.proof.models import Proof
from trust_api.services.scoring import SCORER_VERSION, ScoringResult


class ProofService:
    """Issues (and later verifies) Ed25519-signed trust proofs."""

    def __init__(self, signer: Signer, ttl_hours: int) -> None:
        self._signer = signer
        self._ttl_hours = ttl_hours

    def generate(
        self,
        *,
        wallet: str,
        result: ScoringResult,
        chains: list[str],
        session: Session | None = None,
        now: datetime | None = None,
        nonce: str | None = None,
    ) -> Proof:
        """Build a signed proof for a scoring result (and persist if a session is given)."""
        now = now or datetime.now(UTC)
        expires = now + timedelta(hours=self._ttl_hours)
        payload = build_payload(
            wallet=wallet,
            human_likelihood=result.human_likelihood.value,
            trust_tier=result.trust_tier.value,
            confidence_score=result.confidence_score,
            risk_flags=[f.value for f in result.risk_flags],
            chains=list(chains),
            scorer_version=SCORER_VERSION,
            key_id=self._signer.key_id,
            issued_at=now.isoformat(),
            expires_at=expires.isoformat(),
            nonce=nonce or secrets.token_hex(16),
        )
        signature = base64.b64encode(self._signer.sign(canonical_bytes(payload))).decode("ascii")
        proof = Proof(payload=payload, signature=signature)
        if session is not None:
            self._persist(session, wallet, proof, now, expires)
        return proof

    def _persist(
        self, session: Session, wallet: str, proof: Proof, issued_at: datetime, expires_at: datetime
    ) -> None:
        row = session.execute(select(Wallet).where(Wallet.address == wallet)).scalar_one_or_none()
        if row is None:
            row = Wallet(address=wallet)
            session.add(row)
            session.flush()
        session.add(
            ProofRow(
                wallet_id=row.id,
                payload=proof.payload,
                signature=proof.signature,
                issued_at=issued_at,
                expires_at=expires_at,
                valid_for_hours=self._ttl_hours,
                key_id=proof.key_id,
            )
        )
        session.commit()
