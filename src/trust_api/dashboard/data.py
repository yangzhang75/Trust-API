"""Data-loading layer for the internal dashboard.

Pure query/aggregation functions that read the existing tables + the shared
Redis metrics backend. No Streamlit here — this module is fully unit-tested;
the Streamlit app renders whatever these return.

Time filtering: functions take ``since: datetime | None`` (None = all-time)
and an optional ``now`` for deterministic tests. Scores are read as the
*latest* row per wallet (trust_score_history is append-only per
(wallet, scorer_version)).

Known data-source limits (surfaced, not hidden): the API does not currently
write ``usage_events`` or ``api_keys`` rows, so the usage functions return
empty results today. ``usage_events_present`` lets the UI show a clear
caveat instead of implying zero traffic.
"""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime, timedelta

import redis
from sqlalchemy import func, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from trust_api.core.metrics import METRICS
from trust_api.db.models import (
    ApiKey,
    Proof,
    TrustScoreHistory,
    UsageEvent,
    Wallet,
    WalletFeature,
    WalletTransaction,
)
from trust_api.services.scoring import SCORER_VERSION

TIER_ORDER = ("bronze", "silver", "gold")
LIKELIHOOD_ORDER = ("low", "medium", "high")
CONFIDENCE_BUCKETS = ("0.0–0.2", "0.2–0.4", "0.4–0.6", "0.6–0.8", "0.8–1.0")

# Time-range presets the UI exposes (label -> hours; None = all-time).
TIME_RANGES: dict[str, int | None] = {
    "Last 24h": 24,
    "Last 7d": 24 * 7,
    "Last 30d": 24 * 30,
    "All time": None,
}


def _now(now: datetime | None) -> datetime:
    return now or datetime.now(UTC)


def since_from_hours(hours: int | None, *, now: datetime | None = None) -> datetime | None:
    """Turn a range in hours (or None for all-time) into a cutoff datetime."""
    if hours is None:
        return None
    return _now(now) - timedelta(hours=hours)


# --- overview -------------------------------------------------------------


def current_scorer_version() -> str:
    return SCORER_VERSION


def count_scored_wallets(session: Session, *, since: datetime | None = None) -> int:
    """Distinct wallets with at least one score (optionally within ``since``)."""
    stmt = select(func.count(func.distinct(TrustScoreHistory.wallet_id)))
    if since is not None:
        stmt = stmt.where(TrustScoreHistory.scored_at >= since)
    return int(session.execute(stmt).scalar_one())


def last_scoring_at(session: Session) -> datetime | None:
    """Timestamp of the most recent score — the quick 'is it alive?' signal."""
    return session.execute(select(func.max(TrustScoreHistory.scored_at))).scalar_one()


def _verify_calls(session: Session, *, since: datetime | None = None) -> int:
    stmt = select(func.count(UsageEvent.id)).where(UsageEvent.endpoint == "/verify")
    if since is not None:
        stmt = stmt.where(UsageEvent.created_at >= since)
    return int(session.execute(stmt).scalar_one())


def success_failure_counts(session: Session, *, since: datetime | None = None) -> dict[str, int]:
    """{'success','failure'} counts from usage_events (2xx vs the rest)."""
    stmt = select(UsageEvent.status_code)
    if since is not None:
        stmt = stmt.where(UsageEvent.created_at >= since)
    codes = session.execute(stmt).scalars().all()
    success = sum(1 for c in codes if 200 <= c < 300)
    return {"success": success, "failure": len(codes) - success}


def overview(session: Session, *, now: datetime | None = None) -> dict:
    """Everything the overview panel needs in one call."""
    day = since_from_hours(24, now=now)
    metrics = METRICS.snapshot()
    return {
        "wallets_scored_all_time": count_scored_wallets(session),
        "wallets_scored_24h": count_scored_wallets(session, since=day),
        "verify_calls_all_time": _verify_calls(session),
        "verify_calls_24h": _verify_calls(session, since=day),
        "success_failure_24h": success_failure_counts(session, since=day),
        "avg_scoring_seconds": metrics["scoring_duration_seconds_avg"],
        "wallets_scored_metric": metrics["wallets_scored_total"],
        "wallets_failed_metric": metrics["wallets_failed_total"],
        "last_scoring_at": last_scoring_at(session),
        "scorer_version": current_scorer_version(),
    }


# --- latest score per wallet (shared by distribution + risk panels) -------


def latest_scores(session: Session, *, since: datetime | None = None) -> list[dict]:
    """The most-recent score row per wallet, joined to the wallet address.

    With ``since``, only rows scored on/after the cutoff are considered.
    """
    inner = select(
        TrustScoreHistory.wallet_id,
        TrustScoreHistory.trust_tier,
        TrustScoreHistory.human_likelihood,
        TrustScoreHistory.confidence_score,
        TrustScoreHistory.risk_flags,
        TrustScoreHistory.scorer_version,
        TrustScoreHistory.scored_at,
    )
    if since is not None:
        inner = inner.where(TrustScoreHistory.scored_at >= since)
    inner = (
        inner.distinct(TrustScoreHistory.wallet_id)
        .order_by(TrustScoreHistory.wallet_id, TrustScoreHistory.scored_at.desc())
        .subquery()
    )

    rows = session.execute(
        select(
            Wallet.address,
            inner.c.trust_tier,
            inner.c.human_likelihood,
            inner.c.confidence_score,
            inner.c.risk_flags,
            inner.c.scorer_version,
            inner.c.scored_at,
        ).join(inner, Wallet.id == inner.c.wallet_id)
    ).all()
    return [
        {
            "address": r.address,
            "trust_tier": r.trust_tier,
            "human_likelihood": r.human_likelihood,
            "confidence_score": float(r.confidence_score),
            "risk_flags": list(r.risk_flags or []),
            "scorer_version": r.scorer_version,
            "scored_at": r.scored_at,
        }
        for r in rows
    ]


def _bucket_index(score: float) -> int:
    return min(int(score / 0.2), len(CONFIDENCE_BUCKETS) - 1)


def tier_distribution(session: Session, *, since: datetime | None = None) -> dict[str, int]:
    counts = Counter(s["trust_tier"] for s in latest_scores(session, since=since))
    return {tier: counts.get(tier, 0) for tier in TIER_ORDER}


def likelihood_distribution(session: Session, *, since: datetime | None = None) -> dict[str, int]:
    counts = Counter(s["human_likelihood"] for s in latest_scores(session, since=since))
    return {level: counts.get(level, 0) for level in LIKELIHOOD_ORDER}


def confidence_histogram(session: Session, *, since: datetime | None = None) -> dict[str, int]:
    counts = Counter(
        CONFIDENCE_BUCKETS[_bucket_index(s["confidence_score"])]
        for s in latest_scores(session, since=since)
    )
    return {bucket: counts.get(bucket, 0) for bucket in CONFIDENCE_BUCKETS}


# --- risk flags -----------------------------------------------------------


def risk_flag_frequency(session: Session, *, since: datetime | None = None) -> dict[str, int]:
    """How often each risk flag fires across the latest score per wallet."""
    counts: Counter[str] = Counter()
    for s in latest_scores(session, since=since):
        counts.update(s["risk_flags"])
    return dict(counts.most_common())


def recent_flagged_wallets(
    session: Session, *, since: datetime | None = None, limit: int = 50
) -> list[dict]:
    """Most-recently-scored wallets that carry at least one risk flag."""
    flagged = [s for s in latest_scores(session, since=since) if s["risk_flags"]]
    flagged.sort(key=lambda s: s["scored_at"], reverse=True)
    return flagged[:limit]


# --- wallet inspector -----------------------------------------------------


def _wallet_row(session: Session, address: str) -> Wallet | None:
    return session.execute(select(Wallet).where(Wallet.address == address)).scalar_one_or_none()


def wallet_score_history(session: Session, address: str) -> list[dict]:
    """Every historical score for a wallet, newest first (all scorer versions)."""
    rows = (
        session.execute(
            select(TrustScoreHistory)
            .join(Wallet, Wallet.id == TrustScoreHistory.wallet_id)
            .where(Wallet.address == address)
            .order_by(TrustScoreHistory.scored_at.desc())
        )
        .scalars()
        .all()
    )
    return [
        {
            "trust_tier": r.trust_tier,
            "human_likelihood": r.human_likelihood,
            "confidence_score": float(r.confidence_score),
            "risk_flags": list(r.risk_flags or []),
            "scorer_version": r.scorer_version,
            "scored_at": r.scored_at,
        }
        for r in rows
    ]


def wallet_proofs(session: Session, address: str) -> list[dict]:
    """Proofs issued for a wallet (metadata only — never raw tx data)."""
    rows = (
        session.execute(
            select(Proof)
            .join(Wallet, Wallet.id == Proof.wallet_id)
            .where(Wallet.address == address)
            .order_by(Proof.issued_at.desc())
        )
        .scalars()
        .all()
    )
    return [
        {
            "key_id": r.key_id,
            "issued_at": r.issued_at,
            "expires_at": r.expires_at,
            "valid_for_hours": r.valid_for_hours,
            "revoked": r.revoked,
        }
        for r in rows
    ]


def inspect_wallet(session: Session, address: str) -> dict | None:
    """Everything the system knows about a wallet — the primary 'why this
    score?' tool. Returns None when the wallet is unknown."""
    wallet = _wallet_row(session, address)
    if wallet is None:
        return None
    feature = session.execute(
        select(WalletFeature).where(WalletFeature.wallet_id == wallet.id)
    ).scalar_one_or_none()
    tx_count = session.execute(
        select(func.count(WalletTransaction.id)).where(WalletTransaction.wallet_id == wallet.id)
    ).scalar_one()
    features = None
    if feature is not None:
        features = {
            c.name: getattr(feature, c.name)
            for c in WalletFeature.__table__.columns
            if c.name not in ("id", "wallet_id", "payload")
        }
    return {
        "address": wallet.address,
        "first_seen": wallet.first_seen,
        "last_seen": wallet.last_seen,
        "wallet_tx_count": wallet.tx_count,
        "stored_tx_count": int(tx_count),
        "features": features,
        "score_history": wallet_score_history(session, address),
        "proofs": wallet_proofs(session, address),
    }


# --- API usage (usage_events; see module docstring re: known limits) ------


def usage_events_present(session: Session) -> bool:
    """Whether any usage_events exist — drives the UI 'no data yet' caveat."""
    return session.execute(select(UsageEvent.id).limit(1)).first() is not None


def usage_by_api_key(session: Session, *, since: datetime | None = None) -> list[dict]:
    """Call counts per API key (label from api_keys), most-active first."""
    stmt = (
        select(
            UsageEvent.api_key_id,
            ApiKey.label,
            func.count(UsageEvent.id).label("calls"),
        )
        .join(ApiKey, ApiKey.id == UsageEvent.api_key_id, isouter=True)
        .group_by(UsageEvent.api_key_id, ApiKey.label)
        .order_by(func.count(UsageEvent.id).desc())
    )
    if since is not None:
        stmt = stmt.where(UsageEvent.created_at >= since)
    return [
        {"api_key_id": r.api_key_id, "label": r.label, "calls": int(r.calls)}
        for r in session.execute(stmt).all()
    ]


def rate_limit_hits(session: Session, *, since: datetime | None = None) -> int:
    stmt = select(func.count(UsageEvent.id)).where(UsageEvent.status_code == 429)
    if since is not None:
        stmt = stmt.where(UsageEvent.created_at >= since)
    return int(session.execute(stmt).scalar_one())


def errors_by_status(session: Session, *, since: datetime | None = None) -> dict[int, int]:
    """Counts of failed requests grouped by HTTP status (>= 400)."""
    stmt = (
        select(UsageEvent.status_code, func.count(UsageEvent.id))
        .where(UsageEvent.status_code >= 400)
        .group_by(UsageEvent.status_code)
        .order_by(UsageEvent.status_code)
    )
    if since is not None:
        stmt = stmt.where(UsageEvent.created_at >= since)
    return {int(code): int(n) for code, n in session.execute(stmt).all()}


# --- system health --------------------------------------------------------


def metrics_snapshot() -> dict:
    """Current shared-Redis scoring metrics (same source as GET /metrics)."""
    return METRICS.snapshot()


def db_healthy(session: Session) -> bool:
    try:
        session.execute(text("SELECT 1"))
        return True
    except SQLAlchemyError:
        return False


def redis_healthy(redis_url: str) -> bool:
    try:
        client = redis.from_url(redis_url, socket_connect_timeout=0.5, socket_timeout=0.5)
        client.ping()
        return True
    except redis.RedisError:
        return False
