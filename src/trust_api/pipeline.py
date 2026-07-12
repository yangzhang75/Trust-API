"""End-to-end scoring pipeline: ingest -> features -> score -> persist.

One entry point for a single wallet or a batch. Each wallet runs through
four stages; a failure in any stage is isolated to that wallet (logged,
rolled back) so one bad wallet never breaks a batch. Persistence is
idempotent per scorer_version (append-only history).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from time import perf_counter

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from trust_api.config import Settings
from trust_api.core.logging import get_logger, log_event
from trust_api.core.metrics import METRICS
from trust_api.db.models import TrustScoreHistory, Wallet, WalletFeature
from trust_api.schemas.verify import Chain
from trust_api.services.features import compute_features
from trust_api.services.ingestion import ingest_wallet
from trust_api.services.scoring import SCORER_VERSION, ScoringResult, score

logger = get_logger(__name__)

INGEST_CHAINS = (Chain.ethereum, Chain.arbitrum)
STAGES = ("ingest", "feature", "score", "persist")


def _ms(start: float) -> float:
    return round((perf_counter() - start) * 1000, 3)


class _StageFailed(Exception):
    def __init__(self, stage: str, cause: Exception) -> None:
        self.stage = stage
        self.cause = cause


@dataclass(frozen=True)
class WalletOutcome:
    address: str
    status: str  # "ok" | "error"
    stage: str | None  # failed stage, or None on success
    error_type: str | None
    duration_ms: float
    result: ScoringResult | None


@dataclass(frozen=True)
class BatchSummary:
    total: int
    ok: int
    failed: int
    duration_ms: float
    outcomes: list[WalletOutcome]


async def _ingest(session: Session, address: str, settings: Settings) -> int:
    wallet_id = 0
    for chain in INGEST_CHAINS:
        result = await ingest_wallet(session, address, chain, settings=settings)
        wallet_id = result.wallet_id
    return wallet_id


def _feature_row(session: Session, wallet_id: int) -> WalletFeature:
    return session.execute(
        select(WalletFeature).where(WalletFeature.wallet_id == wallet_id)
    ).scalar_one()


def _persist(session: Session, wallet_id: int, result: ScoringResult, now: datetime) -> None:
    values = {
        "wallet_id": wallet_id,
        "human_likelihood": result.human_likelihood.value,
        "trust_tier": result.trust_tier.value,
        "confidence_score": result.confidence_score,
        "risk_flags": [f.value for f in result.risk_flags],
        "scorer_version": SCORER_VERSION,
        "scored_at": now,
    }
    updatable = ("human_likelihood", "trust_tier", "confidence_score", "risk_flags", "scored_at")
    stmt = (
        pg_insert(TrustScoreHistory)
        .values(**values)
        .on_conflict_do_update(
            index_elements=["wallet_id", "scorer_version"],
            set_={k: values[k] for k in updatable},
        )
    )
    session.execute(stmt)
    session.commit()


def score_wallet(
    session: Session, address: str, settings: Settings, *, now: datetime | None = None
) -> WalletOutcome:
    """Run ingest -> features -> score -> persist for one wallet.

    Any stage failure is isolated: the session is rolled back and an error
    outcome (tagged with the failed stage) is returned, never raised.
    """
    import asyncio

    now = now or datetime.now(UTC)
    ctx = {"wallet": address, "scorer_version": SCORER_VERSION}
    started = perf_counter()

    def run_stage(stage: str, fn):
        t = perf_counter()
        try:
            out = fn()
        except Exception as exc:  # noqa: BLE001 - per-stage isolation
            log_event(
                logger,
                stage=stage,
                status="error",
                error_type=type(exc).__name__,
                duration_ms=_ms(t),
                **ctx,
            )
            session.rollback()
            raise _StageFailed(stage, exc) from exc
        log_event(logger, stage=stage, status="ok", duration_ms=_ms(t), **ctx)
        return out

    try:
        wallet_id = run_stage("ingest", lambda: asyncio.run(_ingest(session, address, settings)))
        run_stage("feature", lambda: compute_features(session, wallet_id, now=now))
        result = run_stage("score", lambda: score(_feature_row(session, wallet_id)))
        run_stage("persist", lambda: _persist(session, wallet_id, result, now))
    except _StageFailed as failed:
        outcome = WalletOutcome(
            address=address,
            status="error",
            stage=failed.stage,
            error_type=type(failed.cause).__name__,
            duration_ms=_ms(started),
            result=None,
        )
    else:
        outcome = WalletOutcome(
            address=address,
            status="ok",
            stage=None,
            error_type=None,
            duration_ms=_ms(started),
            result=result,
        )

    METRICS.record(ok=outcome.status == "ok", duration_seconds=outcome.duration_ms / 1000)
    return outcome


def score_wallets(
    session: Session, addresses: list[str], settings: Settings, *, now: datetime | None = None
) -> BatchSummary:
    """Score a batch of wallets with per-wallet failure isolation."""
    started = perf_counter()
    outcomes = [score_wallet(session, a, settings, now=now) for a in addresses]
    ok = sum(o.status == "ok" for o in outcomes)
    summary = BatchSummary(
        total=len(outcomes),
        ok=ok,
        failed=len(outcomes) - ok,
        duration_ms=_ms(started),
        outcomes=outcomes,
    )
    log_event(
        logger,
        event="batch_summary",
        total=summary.total,
        ok=summary.ok,
        failed=summary.failed,
        duration_ms=summary.duration_ms,
        scorer_version=SCORER_VERSION,
    )
    return summary


def known_wallet_addresses(session: Session) -> list[str]:
    return list(session.execute(select(Wallet.address)).scalars())


def stale_wallet_addresses(
    session: Session, hours: int, *, now: datetime | None = None
) -> list[str]:
    """Addresses whose latest score (this scorer_version) is older than ``hours``."""
    now = now or datetime.now(UTC)
    cutoff = now - _timedelta(hours)
    latest = (
        select(TrustScoreHistory.wallet_id)
        .where(TrustScoreHistory.scorer_version == SCORER_VERSION)
        .where(TrustScoreHistory.scored_at >= cutoff)
        .subquery()
    )
    rows = session.execute(
        select(Wallet.address).where(Wallet.id.not_in(select(latest.c.wallet_id)))
    ).scalars()
    return list(rows)


def _timedelta(hours: int):
    from datetime import timedelta

    return timedelta(hours=hours)
