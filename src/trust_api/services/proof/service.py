"""ProofService — generate and (Week 6 step 4) verify signed proofs."""

from __future__ import annotations

import base64
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from trust_api.core.logging import get_logger
from trust_api.db.models import Proof as ProofRow
from trust_api.db.models import Wallet
from trust_api.services.proof.canonical import build_payload, canonical_bytes
from trust_api.services.proof.keys import Signer
from trust_api.services.proof.models import Proof, VerificationResult
from trust_api.services.proof.offline import verify_offline
from trust_api.services.scoring import SCORER_VERSION, ScoringResult

logger = get_logger(__name__)


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
            self._persist_best_effort(session, wallet, proof, now, expires)
        return proof

    def _persist_best_effort(
        self, session: Session, wallet: str, proof: Proof, issued_at: datetime, expires_at: datetime
    ) -> None:
        """Persist the proof so it can later be revoked; degrade if the DB fails.

        The proof is cryptographically valid regardless of persistence — only
        revocation tracking depends on the row. A DB outage must not fail
        /verify, but it MUST be visible: this proof cannot be revoked.
        """
        try:
            self._persist(session, wallet, proof, issued_at, expires_at)
        except SQLAlchemyError:
            session.rollback()
            logger.warning(
                "proof persistence failed; issued proof is NOT revocable " "(key_id=%s nonce=%s)",
                proof.key_id,
                proof.nonce,
            )

    def verify(
        self, proof: Proof, *, session: Session | None = None, now: datetime | None = None
    ) -> VerificationResult:
        """Verify a proof. Order: unknown_key -> bad_signature -> revoked -> expired -> ok.

        The signature + expiry checks are delegated to ``verify_offline`` (the
        public-key-only path), so the server and an offline third party run the
        SAME verification. This method adds only revocation, which needs our
        database and is checked when a session is provided.
        """
        now = now or datetime.now(UTC)
        result = verify_offline(self._signer.public_key_b64(), proof, now=now)
        # unknown_key / bad_signature short-circuit; otherwise revocation
        # outranks expiry (per the documented order) so check it before
        # returning verify_offline's ok/expired verdict.
        if result.reason in ("unknown_key", "bad_signature"):
            return result
        if session is not None and self._is_revoked(session, proof):
            return VerificationResult(valid=False, reason="revoked", key_id=result.key_id)
        return result

    @staticmethod
    def _is_revoked(session: Session, proof: Proof) -> bool:
        return (
            session.execute(
                select(ProofRow.id).where(
                    ProofRow.signature == proof.signature, ProofRow.revoked.is_(True)
                )
            ).first()
            is not None
        )

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
