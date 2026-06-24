"""FastAPI application factory.

Keeps wiring in one place: configuration, logging, routers, and any
startup/shutdown hooks. Import-time side effects are avoided so the app
is cheap to construct in tests.
"""

from __future__ import annotations

from fastapi import FastAPI

from trust_api.config import Settings, get_settings
from trust_api.core.logging import configure_logging, get_logger


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build and return a configured FastAPI application instance."""
    settings = settings or get_settings()
    configure_logging(settings.log_level)
    logger = get_logger(__name__)

    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        description=(
            "B2B Reputation-as-a-Service API. Week 1 returns deterministic "
            "stub data behind clean typed interfaces."
        ),
    )

    # Stash settings on app.state so dependencies resolve per-app config
    # (lets tests build an app with isolated settings).
    app.state.settings = settings

    @app.get("/health", tags=["meta"], summary="Liveness probe")
    def health() -> dict[str, str]:
        """Return service liveness status."""
        return {"status": "ok"}

    # The /verify router is wired in a later commit.
    from trust_api.api.routes import router as api_router

    app.include_router(api_router)

    logger.info("Trust API initialized (env=%s)", settings.environment)
    return app


# Uvicorn entrypoint: `uvicorn trust_api.main:app`
app = create_app()
