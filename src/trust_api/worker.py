"""Background ingestion worker.

Refreshes wallets on a schedule (APScheduler) or runs a single pass / a
single wallet on demand. Intentionally lightweight — no broker/queue infra.

Usage:
    python -m trust_api.worker                 # run on a schedule
    python -m trust_api.worker --once          # one refresh pass, then exit
    python -m trust_api.worker --wallet 0x...  # ingest one wallet, then exit
"""

from __future__ import annotations

import argparse
import asyncio

from sqlalchemy import select
from sqlalchemy.orm import Session

from trust_api.config import Settings, get_settings
from trust_api.core.logging import configure_logging, get_logger
from trust_api.core.validation import is_valid_evm_wallet
from trust_api.db.models import Wallet
from trust_api.db.session import get_sessionmaker
from trust_api.schemas.verify import Chain
from trust_api.services.features import compute_features_for_wallets
from trust_api.services.ingestion import ingest_wallet
from trust_api.services.ingestion.errors import IngestionError

logger = get_logger(__name__)


async def ingest_wallets(
    session: Session,
    addresses: list[str],
    chain: Chain = Chain.ethereum,
    *,
    settings: Settings | None = None,
) -> dict[str, int | None]:
    """Ingest each address; failures are logged and recorded as None.

    A single wallet's provider failure must not abort the whole pass.
    """
    results: dict[str, int | None] = {}
    for address in addresses:
        if not is_valid_evm_wallet(address):
            logger.warning("skipping invalid wallet address: %s", address)
            results[address] = None
            continue
        try:
            result = await ingest_wallet(session, address, chain, settings=settings)
            results[address] = result.inserted
        except IngestionError as exc:
            logger.warning("ingestion failed for %s: %s", address, exc)
            session.rollback()
            results[address] = None
        except Exception:
            # A single wallet must never abort the whole pass; roll back so
            # the session stays usable for the next wallet.
            logger.exception("unexpected error ingesting %s", address)
            session.rollback()
            results[address] = None
    return results


def _known_wallet_addresses(session: Session) -> list[str]:
    return list(session.execute(select(Wallet.address)).scalars())


def _wallet_ids_for_addresses(session: Session, addresses: list[str]) -> list[int]:
    return list(session.execute(select(Wallet.id).where(Wallet.address.in_(addresses))).scalars())


def _refresh_features(session: Session, addresses: list[str]) -> None:
    """Recompute features for the given addresses after ingestion."""
    wallet_ids = _wallet_ids_for_addresses(session, addresses)
    if wallet_ids:
        compute_features_for_wallets(session, wallet_ids)


def refresh_all() -> dict[str, int | None]:
    """Refresh every wallet currently stored. Used by the scheduled job."""
    session_factory = get_sessionmaker()
    with session_factory() as session:
        addresses = _known_wallet_addresses(session)
        if not addresses:
            logger.info("no wallets to refresh")
            return {}
        logger.info("refreshing %d wallet(s)", len(addresses))
        results = asyncio.run(ingest_wallets(session, addresses))
        _refresh_features(session, addresses)  # features follow ingestion
        return results


def ingest_single(address: str) -> None:
    session_factory = get_sessionmaker()
    with session_factory() as session:
        asyncio.run(ingest_wallets(session, [address]))
        _refresh_features(session, [address])  # features follow ingestion


def scheduled_score() -> dict[str, int]:
    """Scheduled pass: run the full pipeline over wallets with stale scores."""
    from trust_api.config import get_settings
    from trust_api.pipeline import score_wallets, stale_wallet_addresses

    settings = get_settings()
    with get_sessionmaker()() as session:
        addresses = stale_wallet_addresses(session, settings.worker_stale_hours)
        if not addresses:
            logger.info("no stale wallets to score")
            return {"total": 0, "ok": 0, "failed": 0}
        logger.info("scoring %d stale wallet(s)", len(addresses))
        summary = score_wallets(session, addresses, settings)
        return {"total": summary.total, "ok": summary.ok, "failed": summary.failed}


def main(argv: list[str] | None = None) -> None:
    settings = get_settings()
    configure_logging(settings.log_level)

    parser = argparse.ArgumentParser(description="Trust API ingestion worker")
    parser.add_argument("--once", action="store_true", help="run one refresh pass and exit")
    parser.add_argument("--wallet", help="ingest a single wallet address and exit")
    args = parser.parse_args(argv)

    if args.wallet:
        ingest_single(args.wallet)
        return
    if args.once:
        refresh_all()
        return

    # Scheduled mode. Imported lazily so --once/--wallet don't require it.
    from apscheduler.schedulers.blocking import BlockingScheduler

    scheduler = BlockingScheduler()
    # Scheduled work is the full scoring pipeline over stale wallets
    # (ingest -> features -> score -> persist).
    scheduler.add_job(
        scheduled_score,
        "interval",
        seconds=settings.worker_interval_seconds,
        next_run_time=None,
    )
    logger.info("worker started; interval=%ds", settings.worker_interval_seconds)
    scheduler.start()


if __name__ == "__main__":  # pragma: no cover
    main()
