"""Scoring metrics backed by a shared Redis store (Week 6 fix H1).

Counters live in Redis so every process that scores — the API, the batch
CLI, the background worker — writes to the same place, and the API's
`GET /metrics` endpoint reflects real activity regardless of which process
produced it. (Previously the counters were per-process, so the API endpoint
never saw worker/CLI scoring.)

Redis is best-effort: if it is unavailable, recording is skipped and
snapshots read as zero (with a warning) rather than breaking scoring —
consistent with how rate limiting fails open.

The exposition format at `/metrics` is unchanged.
"""

from __future__ import annotations

import redis

from trust_api.config import get_settings
from trust_api.core.logging import get_logger

logger = get_logger(__name__)

_PREFIX = "metrics:"
_SCORED = f"{_PREFIX}wallets_scored_total"
_FAILED = f"{_PREFIX}wallets_failed_total"
_COUNT = f"{_PREFIX}scoring_duration_seconds_count"
_SUM = f"{_PREFIX}scoring_duration_seconds_sum"
_MIN = f"{_PREFIX}scoring_duration_seconds_min"
_MAX = f"{_PREFIX}scoring_duration_seconds_max"
_ALL_KEYS = (_SCORED, _FAILED, _COUNT, _SUM, _MIN, _MAX)

# Atomic "set if smaller / larger" — keeps min/max correct across concurrent
# writers in different processes.
_MIN_LUA = (
    "local c=redis.call('GET',KEYS[1]) "
    "if not c or tonumber(ARGV[1])<tonumber(c) then redis.call('SET',KEYS[1],ARGV[1]) end"
)
_MAX_LUA = (
    "local c=redis.call('GET',KEYS[1]) "
    "if not c or tonumber(ARGV[1])>tonumber(c) then redis.call('SET',KEYS[1],ARGV[1]) end"
)


class _Metrics:
    """Redis-backed scoring counters shared across processes."""

    def __init__(self, client: redis.Redis | None = None) -> None:
        self._client = client

    def _redis(self) -> redis.Redis:
        """Return a process-wide Redis client, created on first use."""
        if self._client is None:
            self._client = redis.from_url(
                get_settings().redis_url,
                decode_responses=True,
                socket_connect_timeout=0.5,
                socket_timeout=0.5,
            )
        return self._client

    def record(self, *, ok: bool, duration_seconds: float) -> None:
        """Record one scoring outcome. Best-effort; never raises on Redis error."""
        try:
            r = self._redis()
            pipe = r.pipeline()
            pipe.incr(_SCORED if ok else _FAILED)
            pipe.incr(_COUNT)
            pipe.incrbyfloat(_SUM, duration_seconds)
            pipe.execute()
            r.eval(_MIN_LUA, 1, _MIN, duration_seconds)
            r.eval(_MAX_LUA, 1, _MAX, duration_seconds)
        except redis.RedisError:
            logger.warning("metrics record skipped; Redis unavailable")

    def snapshot(self) -> dict[str, float]:
        """Return the current counters. Reads as zero if Redis is unavailable."""
        try:
            scored, failed, count, total, mn, mx = self._redis().mget(_ALL_KEYS)
        except redis.RedisError:
            logger.warning("metrics snapshot unavailable; Redis unreachable")
            scored = failed = count = total = mn = mx = None
        count_i = int(count or 0)
        sum_f = float(total or 0.0)
        avg = sum_f / count_i if count_i else 0.0
        return {
            "wallets_scored_total": int(scored or 0),
            "wallets_failed_total": int(failed or 0),
            "scoring_duration_seconds_count": count_i,
            "scoring_duration_seconds_avg": round(avg, 6),
            "scoring_duration_seconds_min": round(float(mn) if mn is not None else 0.0, 6),
            "scoring_duration_seconds_max": round(float(mx) if mx is not None else 0.0, 6),
        }

    def reset(self) -> None:
        """Clear all counters (used by tests). Best-effort."""
        try:
            self._redis().delete(*_ALL_KEYS)
        except redis.RedisError:
            logger.warning("metrics reset skipped; Redis unavailable")


METRICS = _Metrics()

_HELP = {
    "wallets_scored_total": ("counter", "Wallets successfully scored"),
    "wallets_failed_total": ("counter", "Wallets that failed scoring"),
    "scoring_duration_seconds_count": ("gauge", "Number of scoring runs measured"),
    "scoring_duration_seconds_avg": ("gauge", "Average per-wallet scoring duration (s)"),
    "scoring_duration_seconds_min": ("gauge", "Min per-wallet scoring duration (s)"),
    "scoring_duration_seconds_max": ("gauge", "Max per-wallet scoring duration (s)"),
}


def render_prometheus() -> str:
    """Render the current metrics in Prometheus text exposition format."""
    lines: list[str] = []
    for name, value in METRICS.snapshot().items():
        kind, help_text = _HELP[name]
        lines.append(f"# HELP {name} {help_text}")
        lines.append(f"# TYPE {name} {kind}")
        lines.append(f"{name} {value}")
    return "\n".join(lines) + "\n"
