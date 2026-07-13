"""Proof revocation job runner.

Revoking a proof flips its `revoked` flag so ProofService.verify (when
given a DB session) reports reason="revoked". The proof stays
cryptographically valid — revocation is our side channel for saying
"don't trust this anymore" before it expires. An offline verifier with
only the public key cannot see revocation; that is by design.

Usage:
    python -m trust_api.jobs.revoke --proof-id 42
    python -m trust_api.jobs.revoke --wallet 0x...
"""

from __future__ import annotations

import argparse

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from trust_api.config import get_settings
from trust_api.core.logging import configure_logging, get_logger
from trust_api.db.models import Proof, Wallet
from trust_api.db.session import get_sessionmaker

logger = get_logger(__name__)


def revoke_by_id(session: Session, proof_id: int) -> int:
    """Revoke a single proof by primary key. Returns the number revoked (0 or 1)."""
    result = session.execute(
        update(Proof).where(Proof.id == proof_id, Proof.revoked.is_(False)).values(revoked=True)
    )
    session.commit()
    return result.rowcount


def revoke_by_wallet(session: Session, address: str) -> int:
    """Revoke every not-yet-revoked proof for a wallet. Returns the count revoked."""
    wallet_id = session.execute(
        select(Wallet.id).where(Wallet.address == address)
    ).scalar_one_or_none()
    if wallet_id is None:
        return 0
    result = session.execute(
        update(Proof)
        .where(Proof.wallet_id == wallet_id, Proof.revoked.is_(False))
        .values(revoked=True)
    )
    session.commit()
    return result.rowcount


def run(session: Session, args: argparse.Namespace) -> int:
    """Dispatch on the CLI mode and return how many proofs were revoked."""
    if args.proof_id is not None:
        return revoke_by_id(session, args.proof_id)
    return revoke_by_wallet(session, args.wallet)


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Revoke issued trust proofs")
    target = p.add_mutually_exclusive_group(required=True)
    target.add_argument("--proof-id", type=int, help="revoke a single proof by id")
    target.add_argument("--wallet", help="revoke every proof issued for a wallet address")
    return p


def main(argv: list[str] | None = None) -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    args = _parser().parse_args(argv)
    with get_sessionmaker()() as session:
        count = run(session, args)
    target = f"proof-id={args.proof_id}" if args.proof_id is not None else f"wallet={args.wallet}"
    logger.info("revocation complete: %s revoked=%d", target, count)


if __name__ == "__main__":  # pragma: no cover
    main()
