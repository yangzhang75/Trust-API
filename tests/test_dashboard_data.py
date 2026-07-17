"""Tests for the dashboard data-loading layer.

Seeds a real Postgres with known scores/features/proofs/usage and asserts the
counts, distributions, and shapes each panel relies on.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from trust_api.dashboard import data
from trust_api.db.models import (
    Proof,
    TrustScoreHistory,
    UsageEvent,
    Wallet,
    WalletFeature,
    WalletTransaction,
)
from trust_api.services.scoring import SCORER_VERSION

NOW = datetime(2026, 7, 16, 12, 0, tzinfo=UTC)


def _wallet(session: Session, address: str, **kw) -> int:
    w = Wallet(address=address, **kw)
    session.add(w)
    session.flush()
    return w.id


def _score(
    session: Session,
    wallet_id: int,
    *,
    tier="silver",
    likelihood="medium",
    conf=0.5,
    flags=None,
    version=SCORER_VERSION,
    scored_at=NOW,
) -> None:
    session.add(
        TrustScoreHistory(
            wallet_id=wallet_id,
            trust_tier=tier,
            human_likelihood=likelihood,
            confidence_score=conf,
            risk_flags=flags or [],
            scorer_version=version,
            scored_at=scored_at,
        )
    )


def _usage(
    session: Session, endpoint="/verify", status=200, *, when=NOW, api_key_hash=None
) -> None:
    session.add(
        UsageEvent(
            endpoint=endpoint, status_code=status, created_at=when, api_key_hash=api_key_hash
        )
    )


# --- overview -------------------------------------------------------------


def test_since_from_hours() -> None:
    assert data.since_from_hours(None) is None
    assert data.since_from_hours(24, now=NOW) == NOW - timedelta(hours=24)


def test_current_scorer_version() -> None:
    assert data.current_scorer_version() == SCORER_VERSION


def test_count_scored_wallets_all_and_windowed(db_session: Session) -> None:
    w1 = _wallet(db_session, "0x" + "1" * 40)
    w2 = _wallet(db_session, "0x" + "2" * 40)
    _score(db_session, w1, scored_at=NOW)  # fresh
    _score(db_session, w2, scored_at=NOW - timedelta(hours=48))  # old
    db_session.commit()

    assert data.count_scored_wallets(db_session) == 2
    day = data.since_from_hours(24, now=NOW)
    assert data.count_scored_wallets(db_session, since=day) == 1  # only the fresh one


def test_last_scoring_at_none_then_value(db_session: Session) -> None:
    assert data.last_scoring_at(db_session) is None
    w = _wallet(db_session, "0x" + "1" * 40)
    _score(db_session, w, scored_at=NOW)
    db_session.commit()
    assert data.last_scoring_at(db_session) == NOW


def test_success_failure_counts(db_session: Session) -> None:
    _usage(db_session, status=200)
    _usage(db_session, status=201)
    _usage(db_session, status=429)
    _usage(db_session, status=500, when=NOW - timedelta(hours=48))
    db_session.commit()

    all_counts = data.success_failure_counts(db_session)
    assert all_counts == {"success": 2, "failure": 2}
    day = data.since_from_hours(24, now=NOW)
    assert data.success_failure_counts(db_session, since=day) == {"success": 2, "failure": 1}


def test_overview_shape(db_session: Session, metrics_redis) -> None:
    from trust_api.core.metrics import METRICS

    METRICS.record(ok=True, duration_seconds=0.4)
    w = _wallet(db_session, "0x" + "1" * 40)
    _score(db_session, w, scored_at=NOW)
    db_session.commit()

    ov = data.overview(db_session, now=NOW)
    assert ov["wallets_scored_all_time"] == 1
    assert ov["wallets_scored_24h"] == 1
    assert ov["verify_calls_all_time"] == 0  # usage_events empty (known limit)
    assert ov["success_failure_24h"] == {"success": 0, "failure": 0}
    assert ov["avg_scoring_seconds"] == 0.4
    assert ov["wallets_scored_metric"] == 1
    assert ov["last_scoring_at"] == NOW
    assert ov["scorer_version"] == SCORER_VERSION


# --- latest scores + distributions ----------------------------------------


def test_latest_scores_picks_newest_per_wallet(db_session: Session) -> None:
    w = _wallet(db_session, "0x" + "1" * 40)
    _score(db_session, w, tier="bronze", version="0.1.0", scored_at=NOW - timedelta(days=2))
    _score(db_session, w, tier="gold", version="0.2.0", scored_at=NOW)  # newest
    db_session.commit()

    latest = data.latest_scores(db_session)
    assert len(latest) == 1
    assert latest[0]["trust_tier"] == "gold"
    assert latest[0]["scorer_version"] == "0.2.0"


def test_latest_scores_since_filter(db_session: Session) -> None:
    w = _wallet(db_session, "0x" + "1" * 40)
    _score(db_session, w, scored_at=NOW - timedelta(hours=48))
    db_session.commit()
    day = data.since_from_hours(24, now=NOW)
    assert data.latest_scores(db_session, since=day) == []


def test_tier_and_likelihood_distribution(db_session: Session) -> None:
    for i, (tier, lk) in enumerate(
        [("gold", "high"), ("gold", "high"), ("silver", "medium"), ("bronze", "low")]
    ):
        w = _wallet(db_session, f"0x{i:040x}")
        _score(db_session, w, tier=tier, likelihood=lk)
    db_session.commit()

    assert data.tier_distribution(db_session) == {"bronze": 1, "silver": 1, "gold": 2}
    assert data.likelihood_distribution(db_session) == {"low": 1, "medium": 1, "high": 2}


def test_confidence_histogram_buckets(db_session: Session) -> None:
    for i, conf in enumerate([0.0, 0.15, 0.35, 0.55, 0.75, 0.95, 1.0]):
        w = _wallet(db_session, f"0x{i:040x}")
        _score(db_session, w, conf=conf)
    db_session.commit()
    hist = data.confidence_histogram(db_session)
    assert hist == {
        "0.0–0.2": 2,  # 0.0, 0.15
        "0.2–0.4": 1,  # 0.35
        "0.4–0.6": 1,  # 0.55
        "0.6–0.8": 1,  # 0.75
        "0.8–1.0": 2,  # 0.95, 1.0 (1.0 clamps into the top bucket)
    }


# --- risk flags -----------------------------------------------------------


def test_risk_flag_frequency(db_session: Session) -> None:
    w1 = _wallet(db_session, "0x" + "1" * 40)
    w2 = _wallet(db_session, "0x" + "2" * 40)
    w3 = _wallet(db_session, "0x" + "3" * 40)
    _score(db_session, w1, flags=["low_activity", "new_wallet"])
    _score(db_session, w2, flags=["low_activity"])
    _score(db_session, w3, flags=[])  # clean wallet, no flags
    db_session.commit()

    freq = data.risk_flag_frequency(db_session)
    assert freq["low_activity"] == 2
    assert freq["new_wallet"] == 1
    assert "sybil_suspected" not in freq


def test_recent_flagged_wallets_filters_sorts_limits(db_session: Session) -> None:
    w1 = _wallet(db_session, "0x" + "1" * 40)
    w2 = _wallet(db_session, "0x" + "2" * 40)
    w3 = _wallet(db_session, "0x" + "3" * 40)
    _score(db_session, w1, flags=["bot_burst"], scored_at=NOW - timedelta(hours=2))
    _score(db_session, w2, flags=["dormant"], scored_at=NOW)  # newest flagged
    _score(db_session, w3, flags=[], scored_at=NOW)  # clean, excluded
    db_session.commit()

    flagged = data.recent_flagged_wallets(db_session)
    assert [f["address"] for f in flagged] == ["0x" + "2" * 40, "0x" + "1" * 40]
    assert data.recent_flagged_wallets(db_session, limit=1)[0]["address"] == "0x" + "2" * 40


# --- wallet inspector -----------------------------------------------------


def test_inspect_unknown_wallet_returns_none(db_session: Session) -> None:
    assert data.inspect_wallet(db_session, "0x" + "9" * 40) is None


def test_inspect_wallet_full(db_session: Session) -> None:
    addr = "0x" + "1" * 40
    w = _wallet(db_session, addr, tx_count=3, first_seen=NOW, last_seen=NOW)
    db_session.add(
        WalletFeature(wallet_id=w, chain="ethereum", payload={}, tx_count=3, wallet_age_days=100)
    )
    db_session.add(
        WalletTransaction(
            wallet_id=w,
            chain="ethereum",
            tx_hash="0x" + "a" * 64,
            block_number=1,
            block_time=NOW,
            value_wei=1,
            direction="out",
            counterparty="0x" + "b" * 40,
        )
    )
    _score(db_session, w, tier="gold", version="0.1.0", scored_at=NOW - timedelta(days=1))
    _score(db_session, w, tier="silver", version="0.2.0", scored_at=NOW)
    db_session.add(
        Proof(
            wallet_id=w,
            payload={"wallet": addr},
            signature="sig",
            issued_at=NOW,
            expires_at=NOW + timedelta(hours=1),
            valid_for_hours=1,
            key_id="k" * 16,
        )
    )
    db_session.commit()

    info = data.inspect_wallet(db_session, addr)
    assert info["address"] == addr
    assert info["wallet_tx_count"] == 3
    assert info["stored_tx_count"] == 1
    assert info["features"]["wallet_age_days"] == 100
    assert "payload" not in info["features"] and "id" not in info["features"]
    # full history, newest first, both versions
    assert [h["scorer_version"] for h in info["score_history"]] == ["0.2.0", "0.1.0"]
    assert len(info["proofs"]) == 1 and info["proofs"][0]["revoked"] is False


def test_inspect_wallet_without_features(db_session: Session) -> None:
    addr = "0x" + "2" * 40
    _wallet(db_session, addr)  # registered, no feature row
    db_session.commit()
    info = data.inspect_wallet(db_session, addr)
    assert info["features"] is None
    assert info["score_history"] == [] and info["proofs"] == []


# --- API usage ------------------------------------------------------------


def test_usage_events_present(db_session: Session) -> None:
    assert data.usage_events_present(db_session) is False
    _usage(db_session)
    db_session.commit()
    assert data.usage_events_present(db_session) is True


def test_usage_by_api_key(db_session: Session) -> None:
    assert data.usage_by_api_key(db_session) == []  # no usage yet
    _usage(db_session, api_key_hash="abc123")
    _usage(db_session, api_key_hash="abc123")
    _usage(db_session, api_key_hash=None)  # unauthenticated / invalid key
    db_session.commit()

    rows = data.usage_by_api_key(db_session, since=data.since_from_hours(24, now=NOW))
    by_hash = {r["api_key_hash"]: r["calls"] for r in rows}
    assert by_hash["abc123"] == 2
    assert by_hash[None] == 1


def test_rate_limit_hits_and_errors_by_status(db_session: Session) -> None:
    for status in (200, 400, 401, 422, 429, 429, 500):
        _usage(db_session, status=status)
    _usage(db_session, status=429, when=NOW - timedelta(hours=48))  # old
    db_session.commit()

    assert data.rate_limit_hits(db_session) == 3
    day = data.since_from_hours(24, now=NOW)
    assert data.rate_limit_hits(db_session, since=day) == 2
    # all-time (since=None) includes the old 429
    assert data.errors_by_status(db_session) == {400: 1, 401: 1, 422: 1, 429: 3, 500: 1}
    assert data.errors_by_status(db_session, since=day) == {400: 1, 401: 1, 422: 1, 429: 2, 500: 1}


# --- system health --------------------------------------------------------


def test_metrics_snapshot(metrics_redis) -> None:
    from trust_api.core.metrics import METRICS

    METRICS.record(ok=False, duration_seconds=0.2)
    snap = data.metrics_snapshot()
    assert snap["wallets_failed_total"] == 1


def test_db_healthy_true_and_false(db_session: Session) -> None:
    assert data.db_healthy(db_session) is True
    broken = MagicMock()
    broken.execute.side_effect = SQLAlchemyError("db down")
    assert data.db_healthy(broken) is False


def test_redis_healthy_true_and_false() -> None:
    import os

    url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
    assert data.redis_healthy(url) is True
    assert data.redis_healthy("redis://localhost:6399/0") is False  # dead port
