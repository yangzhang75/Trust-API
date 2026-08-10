"""Local metrics store for the mock platform (SQLite — NOT the Trust API's DB).

Records one row per decision (login/creator/filter) and aggregates them for
GET /mock/stats. A single connection guarded by a lock keeps it thread-safe
across FastAPI's threadpool; ``:memory:`` (the default) keeps tests file-free,
while the demo points MOCK_DB_PATH at a real file for persistence.
"""

from __future__ import annotations

import sqlite3
import threading
from datetime import UTC, datetime, timedelta

_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    scenario   TEXT    NOT NULL,
    wallet     TEXT    NOT NULL,
    accepted   INTEGER NOT NULL,
    tier       TEXT    NOT NULL,
    reason     TEXT    NOT NULL,
    latency_ms REAL    NOT NULL,
    ts         TEXT    NOT NULL
)
"""

# Accounts registered via an accepted login — the state the hybrid background
# re-score job updates (and may retroactively suspend).
_ACCOUNTS_SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
    wallet           TEXT PRIMARY KEY,
    status           TEXT NOT NULL,
    tier             TEXT NOT NULL,
    last_login_at    TEXT NOT NULL,
    suspended_reason TEXT,
    suspended_at     TEXT
)
"""


class MetricsStore:
    def __init__(self, db_path: str) -> None:
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._lock = threading.Lock()
        with self._lock:
            self._conn.execute(_SCHEMA)
            self._conn.execute(_ACCOUNTS_SCHEMA)
            self._conn.commit()

    def record(
        self,
        *,
        scenario: str,
        wallet: str,
        accepted: bool,
        tier: str,
        reason: str,
        latency_ms: float,
        ts: str | None = None,
    ) -> None:
        ts = ts or datetime.now(UTC).isoformat()
        with self._lock:
            self._conn.execute(
                "INSERT INTO events VALUES (?, ?, ?, ?, ?, ?, ?)",
                (scenario, wallet, int(accepted), tier, reason, latency_ms, ts),
            )
            self._conn.commit()

    def stats(self) -> dict:
        """Per-scenario totals, accept/reject, acceptance rate, avg latency, and
        tier + reason breakdowns."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT scenario, accepted, tier, reason, latency_ms FROM events"
            ).fetchall()

        agg: dict[str, dict] = {}
        for scenario, accepted, tier, reason, latency in rows:
            s = agg.setdefault(
                scenario,
                {"total": 0, "accepted": 0, "latency_sum": 0.0, "tiers": {}, "reasons": {}},
            )
            s["total"] += 1
            s["accepted"] += int(accepted)
            s["latency_sum"] += latency
            s["tiers"][tier] = s["tiers"].get(tier, 0) + 1
            s["reasons"][reason] = s["reasons"].get(reason, 0) + 1

        return {
            scenario: {
                "total": s["total"],
                "accepted": s["accepted"],
                "rejected": s["total"] - s["accepted"],
                "acceptance_rate": round(s["accepted"] / s["total"], 3),
                "avg_latency_ms": round(s["latency_sum"] / s["total"], 2),
                "tiers": s["tiers"],
                "reasons": s["reasons"],
            }
            for scenario, s in agg.items()
        }

    # --- accounts (hybrid re-score) --------------------------------------

    def upsert_account(self, wallet: str, tier: str, *, now: str | None = None) -> None:
        """Register/refresh an active account on an accepted login."""
        now = now or datetime.now(UTC).isoformat()
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO accounts (wallet, status, tier, last_login_at)
                VALUES (?, 'active', ?, ?)
                ON CONFLICT(wallet) DO UPDATE SET
                    status='active', tier=excluded.tier, last_login_at=excluded.last_login_at,
                    suspended_reason=NULL, suspended_at=NULL
                """,
                (wallet, tier, now),
            )
            self._conn.commit()

    def recent_active_accounts(
        self, since_minutes: int, *, now: datetime | None = None
    ) -> list[str]:
        """Active accounts whose last login is within the window (for re-score)."""
        now = now or datetime.now(UTC)
        cutoff = (now - timedelta(minutes=since_minutes)).isoformat()
        with self._lock:
            rows = self._conn.execute(
                "SELECT wallet FROM accounts WHERE status='active' AND last_login_at >= ?",
                (cutoff,),
            ).fetchall()
        return [r[0] for r in rows]

    def suspend_account(self, wallet: str, reason: str, *, now: str | None = None) -> None:
        now = now or datetime.now(UTC).isoformat()
        with self._lock:
            self._conn.execute(
                "UPDATE accounts SET status='suspended', suspended_reason=?, suspended_at=? "
                "WHERE wallet=?",
                (reason, now, wallet),
            )
            self._conn.commit()

    def account(self, wallet: str) -> dict | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT wallet, status, tier, suspended_reason FROM accounts WHERE wallet=?",
                (wallet,),
            ).fetchone()
        if row is None:
            return None
        return {"wallet": row[0], "status": row[1], "tier": row[2], "suspended_reason": row[3]}

    def close(self) -> None:
        self._conn.close()
