"""FastAPI dependencies.

Week 1 provides settings resolution. API-key auth and Redis rate limiting
are layered on in a later commit.
"""

from __future__ import annotations

from fastapi import Request

from trust_api.config import Settings


def get_settings(request: Request) -> Settings:
    """Resolve the app's Settings, stashed on app.state by the factory."""
    return request.app.state.settings
