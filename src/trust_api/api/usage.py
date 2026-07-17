"""Request usage logging (Week 8).

A FastAPI middleware records one ``usage_events`` row per request *after* the
response is produced, via a Starlette background task so it never delays or
fails the request. If the write fails (e.g. DB down) it logs a warning and
moves on — the same graceful-degradation discipline used elsewhere.

The API key is stored only as ``sha256(key)[:16]`` of a *valid* allowlist
key (privacy-preserving); unauthenticated/invalid requests record NULL.
"""

from __future__ import annotations

import hashlib
from time import perf_counter

from sqlalchemy.exc import SQLAlchemyError
from starlette.background import BackgroundTask

from trust_api.config import Settings
from trust_api.core.logging import get_logger
from trust_api.db.models import UsageEvent

logger = get_logger(__name__)

API_KEY_HEADER = "X-API-Key"


def hash_api_key(api_key: str | None, settings: Settings) -> str | None:
    """Return sha256(key)[:16] iff the key is a configured allowlist key.

    Returns None for a missing key or one not in the allowlist, so invalid /
    unauthenticated requests are recorded without any key material.
    """
    if api_key and api_key in settings.api_key_set:
        return hashlib.sha256(api_key.encode("utf-8")).hexdigest()[:16]
    return None


def record_usage(
    session_factory,
    *,
    endpoint: str,
    method: str,
    status_code: int,
    api_key_hash: str | None,
    duration_ms: float,
) -> None:
    """Best-effort insert of one usage_events row. Never raises."""
    try:
        with session_factory() as session:
            session.add(
                UsageEvent(
                    endpoint=endpoint,
                    method=method,
                    status_code=status_code,
                    api_key_hash=api_key_hash,
                    response_duration_ms=duration_ms,
                )
            )
            session.commit()
    except SQLAlchemyError:
        logger.warning(
            "usage_events write failed; request unaffected (endpoint=%s status=%s)",
            endpoint,
            status_code,
        )


def install_usage_logging(app) -> None:
    """Register the usage-logging middleware on ``app``.

    Uses ``app.state.session_factory`` for the write so tests can point it at
    a test database.
    """

    @app.middleware("http")
    async def _usage_middleware(request, call_next):
        start = perf_counter()
        response = await call_next(request)
        duration_ms = round((perf_counter() - start) * 1000, 3)
        response.background = BackgroundTask(
            record_usage,
            request.app.state.session_factory,
            endpoint=request.url.path,
            method=request.method,
            status_code=response.status_code,
            api_key_hash=hash_api_key(
                request.headers.get(API_KEY_HEADER), request.app.state.settings
            ),
            duration_ms=duration_ms,
        )
        return response
