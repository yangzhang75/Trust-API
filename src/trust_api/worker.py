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
from trust_api.db.models import Wallet
from trust_api.db.session import get_sessionmaker
from trust_api.schemas.verify import Chain
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
        try:
            result = await ingest_wallet(session, address, chain, settings=settings)
            results[address] = result.inserted
        except IngestionError as exc:
            logger.warning("ingestion failed for %s: %s", address, exc)
            results[address] = None
    return results


def _known_wallet_addresses(session: Session) -> list[str]:
    return list(session.execute(select(Wallet.address)).scalars())


def refresh_all() -> dict[str, int | None]:
    """Refresh every wallet currently stored. Used by the scheduled job."""
    session_factory = get_sessionmaker()
    with session_factory() as session:
        addresses = _known_wallet_addresses(session)
        if not addresses:
            logger.info("no wallets to refresh")
            return {}
        logger.info("refreshing %d wallet(s)", len(addresses))
        return asyncio.run(ingest_wallets(session, addresses))


def ingest_single(address: str) -> None:
    session_factory = get_sessionmaker()
    with session_factory() as session:
        asyncio.run(ingest_wallets(session, [address]))


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
    scheduler.add_job(
        refresh_all,
        "interval",
        seconds=settings.worker_interval_seconds,
        next_run_time=None,
    )
    logger.info("worker started; interval=%ds", settings.worker_interval_seconds)
    scheduler.start()


if __name__ == "__main__":  # pragma: no cover
    main()
