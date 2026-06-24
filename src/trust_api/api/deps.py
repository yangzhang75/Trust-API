"""FastAPI dependencies: settings, API-key auth, and Redis rate limiting."""

from __future__ import annotations

import time
from typing import Annotated

import redis
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import APIKeyHeader

from trust_api.config import Settings
from trust_api.core.logging import get_logger

logger = get_logger(__name__)

API_KEY_HEADER = "X-API-Key"
_api_key_scheme = APIKeyHeader(name=API_KEY_HEADER, auto_error=False)


def get_settings(request: Request) -> Settings:
    """Resolve the app's Settings, stashed on app.state by the factory."""
    return request.app.state.settings


SettingsDep = Annotated[Settings, Depends(get_settings)]


def require_api_key(
    settings: SettingsDep,
    api_key: Annotated[str | None, Depends(_api_key_scheme)] = None,
) -> str:
    """Validate the X-API-Key header against the configured allowlist.

    Returns the validated key. Raises 401 when missing or unknown. With no
    keys configured the API is closed (every request is rejected).
    """
    if not api_key or api_key not in settings.api_key_set:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid API key.",
            headers={"WWW-Authenticate": API_KEY_HEADER},
        )
    return api_key


def get_redis(request: Request, settings: SettingsDep) -> redis.Redis:
    """Return a process-wide Redis client, cached on app.state."""
    client = getattr(request.app.state, "redis", None)
    if client is None:
        client = redis.from_url(
            settings.redis_url,
            decode_responses=True,
            socket_connect_timeout=0.5,
            socket_timeout=0.5,
        )
        request.app.state.redis = client
    return client


def rate_limit(
    settings: SettingsDep,
    api_key: Annotated[str, Depends(require_api_key)],
    r: Annotated[redis.Redis, Depends(get_redis)],
) -> None:
    """Enforce a fixed-window per-minute limit per API key, backed by Redis.

    Fails open if Redis is unreachable so a cache outage does not take the
    API down. TODO(week2): decide whether abuse-sensitive routes should
    instead fail closed, and move to a sliding-window/token-bucket scheme.
    """
    limit = settings.rate_limit_per_minute
    window = int(time.time() // 60)
    key = f"ratelimit:{api_key}:{window}"
    try:
        count = r.incr(key)
        if count == 1:
            r.expire(key, 60)
    except redis.RedisError:
        logger.warning("Redis unavailable; rate limiting failing open")
        return

    if count > limit:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded.",
            headers={"Retry-After": "60"},
        )
