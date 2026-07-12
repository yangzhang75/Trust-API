"""Minimal in-process metrics for the scoring pipeline (Week 5).

Deliberately tiny: module-level counters + a duration accumulator, no
external dependency. Exposed at GET /metrics in Prometheus text format.

Caveat: these counters live in ONE process. The API process only reflects
scoring done in-process; a separate worker process has its own counters. A
shared metrics backend is out of scope this week.
"""

from __future__ import annotations

import threading


class _Metrics:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.reset()

    def reset(self) -> None:
        self.scored_total = 0
        self.failed_total = 0
        self._dur_count = 0
        self._dur_sum = 0.0
        self._dur_min: float | None = None
        self._dur_max: float | None = None

    def record(self, *, ok: bool, duration_seconds: float) -> None:
        with self._lock:
            if ok:
                self.scored_total += 1
            else:
                self.failed_total += 1
            self._dur_count += 1
            self._dur_sum += duration_seconds
            self._dur_min = (
                duration_seconds if self._dur_min is None else min(self._dur_min, duration_seconds)
            )
            self._dur_max = (
                duration_seconds if self._dur_max is None else max(self._dur_max, duration_seconds)
            )

    def snapshot(self) -> dict[str, float]:
        avg = self._dur_sum / self._dur_count if self._dur_count else 0.0
        return {
            "wallets_scored_total": self.scored_total,
            "wallets_failed_total": self.failed_total,
            "scoring_duration_seconds_count": self._dur_count,
            "scoring_duration_seconds_avg": round(avg, 6),
            "scoring_duration_seconds_min": round(self._dur_min or 0.0, 6),
            "scoring_duration_seconds_max": round(self._dur_max or 0.0, 6),
        }


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
