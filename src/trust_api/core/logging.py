"""Logging configuration for the Trust API.

Stdlib logging with a single stream handler, plus a small structured
(JSON) event helper for the scoring pipeline (Week 5).
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime

_CONFIGURED = False


def configure_logging(level: str = "INFO") -> None:
    """Configure root logging once for the process."""
    global _CONFIGURED
    if _CONFIGURED:
        return

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S%z",
        )
    )

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper())

    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    """Return a named logger."""
    return logging.getLogger(name)


def log_event(logger: logging.Logger, **fields: object) -> None:
    """Emit one structured (JSON) log line.

    A ``ts`` timestamp is added automatically. Callers pass only
    aggregated/metadata fields (wallet, stage, status, duration_ms, ...) —
    never raw transaction content (privacy requirement).
    """
    payload = {"ts": datetime.now(UTC).isoformat(), **fields}
    logger.info(json.dumps(payload, default=str))
