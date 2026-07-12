"""Scoring job runner.

Usage:
    python -m trust_api.jobs.score --wallet 0x...
    python -m trust_api.jobs.score --batch addresses.txt
    python -m trust_api.jobs.score --refresh-stale --hours 24
    python -m trust_api.jobs.score --refresh-all
"""

from __future__ import annotations

import argparse
from pathlib import Path

from sqlalchemy.orm import Session

from trust_api.config import Settings, get_settings
from trust_api.core.logging import configure_logging, get_logger
from trust_api.db.session import get_sessionmaker
from trust_api.pipeline import (
    BatchSummary,
    known_wallet_addresses,
    score_wallets,
    stale_wallet_addresses,
)

logger = get_logger(__name__)


def resolve_addresses(session: Session, args: argparse.Namespace) -> list[str]:
    """Turn CLI mode flags into the concrete list of addresses to score."""
    if args.wallet:
        return [args.wallet]
    if args.batch:
        text = Path(args.batch).read_text(encoding="utf-8")
        return [line.strip() for line in text.splitlines() if line.strip()]
    if args.refresh_stale:
        return stale_wallet_addresses(session, args.hours)
    return known_wallet_addresses(session)  # --refresh-all / default


def run(session: Session, addresses: list[str], settings: Settings) -> BatchSummary:
    return score_wallets(session, addresses, settings)


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Score wallets and persist history")
    p.add_argument("--wallet", help="score a single wallet address")
    p.add_argument("--batch", help="score all addresses in a file (one per line)")
    p.add_argument("--refresh-stale", action="store_true", help="score wallets with stale scores")
    p.add_argument("--hours", type=int, default=24, help="staleness threshold for --refresh-stale")
    p.add_argument("--refresh-all", action="store_true", help="score every known wallet")
    return p


def main(argv: list[str] | None = None) -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    args = _parser().parse_args(argv)
    with get_sessionmaker()() as session:
        addresses = resolve_addresses(session, args)
        summary = run(session, addresses, settings)
    logger.info(
        "scoring complete: total=%d ok=%d failed=%d",
        summary.total,
        summary.ok,
        summary.failed,
    )


if __name__ == "__main__":  # pragma: no cover
    main()
