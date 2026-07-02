"""Batch job: compute behavioral features for wallets.

Usage:
    python -m trust_api.jobs.compute_features                 # all wallets w/ txs
    python -m trust_api.jobs.compute_features --all           # (same as default)
    python -m trust_api.jobs.compute_features --wallet-id 1 --wallet-id 2
"""

from __future__ import annotations

import argparse

from sqlalchemy.orm import Session

from trust_api.config import get_settings
from trust_api.core.logging import configure_logging, get_logger
from trust_api.db.session import get_sessionmaker
from trust_api.services.features import (
    all_wallet_ids_with_transactions,
    compute_features_for_wallets,
)

logger = get_logger(__name__)


def run(session: Session, wallet_ids: list[int] | None = None) -> dict[int, bool]:
    """Compute features for the given wallet ids, or all wallets with txs."""
    ids = wallet_ids if wallet_ids else all_wallet_ids_with_transactions(session)
    if not ids:
        logger.info("no wallets to compute features for")
        return {}
    logger.info("computing features for %d wallet(s)", len(ids))
    return compute_features_for_wallets(session, ids)


def main(argv: list[str] | None = None) -> None:
    settings = get_settings()
    configure_logging(settings.log_level)

    parser = argparse.ArgumentParser(description="Compute wallet behavioral features")
    parser.add_argument(
        "--wallet-id",
        type=int,
        action="append",
        dest="wallet_ids",
        help="wallet id (repeatable); default = all wallets with transactions",
    )
    parser.add_argument(
        "--all", action="store_true", help="compute for all wallets with transactions (default)"
    )
    args = parser.parse_args(argv)

    with get_sessionmaker()() as session:
        results = run(session, args.wallet_ids)
    logger.info("feature computation complete: %s", results)


if __name__ == "__main__":  # pragma: no cover
    main()
