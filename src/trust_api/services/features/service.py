"""Feature service — compute per-wallet behavioral features from the DB.

Reads wallet_transactions with SQL aggregation (never pulls full history
into Python) and upserts the result into wallet_features. Deterministic
given the stored data and a reference ``now`` (injected for testability).
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import distinct, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from trust_api.core.logging import get_logger
from trust_api.db.models import WalletFeature, WalletTransaction
from trust_api.schemas.verify import Chain
from trust_api.services.features.models import WalletFeatures

logger = get_logger(__name__)

DORMANCY_DAYS = 90
_FEATURE_COLUMNS = (
    "wallet_age_days",
    "tx_count",
    "active_days",
    "tx_per_active_day",
    "counterparty_count",
    "counterparty_diversity_ratio",
    "inbound_ratio",
    "burst_score",
    "dormancy_flag",
    "recency_days",
    "computed_at",
)


def _utc(col):
    """A timestamp column projected into UTC (naive), for stable date math."""
    return func.timezone("UTC", col)


def compute_features(
    session: Session, wallet_id: int, *, now: datetime | None = None
) -> WalletFeatures:
    """Compute the 10 behavioral features for ``wallet_id`` and upsert them."""
    now = now or datetime.now(UTC)
    tx = WalletTransaction

    agg = session.execute(
        select(
            func.count().label("tx_count"),
            func.count(distinct(func.date(_utc(tx.block_time)))).label("active_days"),
            func.count(distinct(tx.counterparty)).label("counterparty_count"),
            func.count().filter(tx.direction == "in").label("inbound_count"),
            func.min(tx.block_time).label("first_seen"),
            func.max(tx.block_time).label("last_seen"),
        ).where(tx.wallet_id == wallet_id)
    ).one()

    # burst_score: the largest number of transactions in any one-hour window.
    per_hour = (
        select(func.count().label("c"))
        .where(tx.wallet_id == wallet_id)
        .group_by(func.date_trunc("hour", _utc(tx.block_time)))
        .subquery()
    )
    burst_score = session.execute(select(func.coalesce(func.max(per_hour.c.c), 0))).scalar_one()

    tx_count = agg.tx_count or 0
    active_days = agg.active_days or 0
    counterparty_count = agg.counterparty_count or 0
    inbound_count = agg.inbound_count or 0
    first_seen = agg.first_seen
    last_seen = agg.last_seen

    recency_days = (now - last_seen).days if last_seen is not None else 0
    features = WalletFeatures(
        wallet_id=wallet_id,
        chain=Chain.ethereum.value,
        wallet_age_days=(now - first_seen).days if first_seen is not None else 0,
        tx_count=tx_count,
        active_days=active_days,
        tx_per_active_day=round(tx_count / active_days, 6) if active_days else 0.0,
        counterparty_count=counterparty_count,
        counterparty_diversity_ratio=round(counterparty_count / tx_count, 6) if tx_count else 0.0,
        inbound_ratio=round(inbound_count / tx_count, 6) if tx_count else 0.0,
        burst_score=int(burst_score),
        dormancy_flag=last_seen is not None and recency_days > DORMANCY_DAYS,
        recency_days=recency_days,
        computed_at=now,
    )
    _upsert(session, features)
    return features


def _upsert(session: Session, f: WalletFeatures) -> None:
    values = {
        "wallet_id": f.wallet_id,
        "chain": f.chain,
        "payload": {},
        "wallet_age_days": f.wallet_age_days,
        "tx_count": f.tx_count,
        "active_days": f.active_days,
        "tx_per_active_day": f.tx_per_active_day,
        "counterparty_count": f.counterparty_count,
        "counterparty_diversity_ratio": f.counterparty_diversity_ratio,
        "inbound_ratio": f.inbound_ratio,
        "burst_score": f.burst_score,
        "dormancy_flag": f.dormancy_flag,
        "recency_days": f.recency_days,
        "computed_at": f.computed_at,
    }
    stmt = (
        pg_insert(WalletFeature)
        .values(**values)
        .on_conflict_do_update(
            index_elements=["wallet_id", "chain"],
            set_={col: values[col] for col in _FEATURE_COLUMNS},
        )
    )
    session.execute(stmt)
    session.commit()


def all_wallet_ids_with_transactions(session: Session) -> list[int]:
    """Return distinct wallet ids that have at least one stored transaction."""
    return list(session.execute(select(distinct(WalletTransaction.wallet_id))).scalars())


def compute_features_for_wallets(
    session: Session, wallet_ids: list[int], *, now: datetime | None = None
) -> dict[int, bool]:
    """Compute features for many wallets; one failure never aborts the batch."""
    results: dict[int, bool] = {}
    for wallet_id in wallet_ids:
        try:
            compute_features(session, wallet_id, now=now)
            results[wallet_id] = True
        except Exception:
            logger.exception("feature computation failed for wallet_id=%s", wallet_id)
            session.rollback()
            results[wallet_id] = False
    return results
