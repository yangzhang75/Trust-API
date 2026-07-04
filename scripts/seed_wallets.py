"""Seed the labeled sample wallets into Postgres.

Registers each wallet from data/labeled_wallets.json (idempotent) and, if a
provider key is configured, ingests its real transaction history. Without a
key it still registers the wallets so there is data to work with locally.

Usage: python scripts/seed_wallets.py   (or `make seed`)
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from sqlalchemy.orm import Session

from trust_api.config import Settings, get_settings
from trust_api.core.logging import configure_logging, get_logger
from trust_api.schemas.verify import Chain
from trust_api.services.ingestion import load_transactions
from trust_api.worker import ingest_wallets

logger = get_logger(__name__)

DATASET = Path(__file__).resolve().parent.parent / "data" / "labeled_wallets.json"


def load_dataset(path: Path = DATASET) -> list[dict]:
    """Return the list of labeled wallet entries from the dataset file."""
    return json.loads(path.read_text(encoding="utf-8"))["wallets"]


def _chains(entry: dict) -> list[str]:
    return entry.get("chains") or ["ethereum"]


def seed(session: Session, wallets: list[dict], settings: Settings) -> dict[str, int | None]:
    """Register wallets (always) and ingest their history (if a key is set)."""
    for entry in wallets:
        # Empty load upserts the wallet row so labels have something to attach to.
        load_transactions(session, entry["address"], Chain(_chains(entry)[0]), [])

    addresses = [e["address"] for e in wallets]
    if not settings.ingestion_provider_configured:
        logger.warning(
            "ETHERSCAN_API_KEY not set; registered %d wallet(s) without tx history",
            len(wallets),
        )
        return dict.fromkeys(addresses)

    return asyncio.run(ingest_wallets(session, addresses, settings=settings))


def main() -> None:  # pragma: no cover
    from trust_api.db.session import get_sessionmaker

    settings = get_settings()
    configure_logging(settings.log_level)
    with get_sessionmaker()() as session:
        results = seed(session, load_dataset(), settings)
    logger.info("seed complete: %s", results)


if __name__ == "__main__":  # pragma: no cover
    main()
