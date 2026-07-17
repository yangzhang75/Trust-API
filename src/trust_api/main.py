"""FastAPI application factory.

Keeps wiring in one place: configuration, logging, routers, and any
startup/shutdown hooks. Import-time side effects are avoided so the app
is cheap to construct in tests.
"""

from __future__ import annotations

from fastapi import FastAPI, Response

from trust_api.api.usage import install_usage_logging
from trust_api.config import Settings, get_settings
from trust_api.core.logging import configure_logging, get_logger
from trust_api.core.metrics import render_prometheus
from trust_api.db.session import get_sessionmaker
from trust_api.services.proof import load_signer


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build and return a configured FastAPI application instance."""
    settings = settings or get_settings()
    settings.validate_runtime()
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
    # One signing key per process (stable key_id; ephemeral dev key warns).
    app.state.signer = load_signer(settings)
    # Session factory for the usage-logging middleware (tests can override).
    app.state.session_factory = get_sessionmaker()
    install_usage_logging(app)

    @app.get("/health", tags=["meta"], summary="Liveness probe")
    def health() -> dict[str, str]:
        """Return service liveness status."""
        return {"status": "ok"}

    @app.get("/metrics", tags=["meta"], summary="Scoring metrics (Prometheus text)")
    def metrics() -> Response:
        """Expose in-process scoring counters in Prometheus text format."""
        return Response(content=render_prometheus(), media_type="text/plain; version=0.0.4")

    @app.get("/proof/public-key", tags=["proof"], summary="Fetch the proof verification key")
    def public_key() -> dict[str, str]:
        """Public key consumers use to verify proofs locally (no callback)."""
        signer = app.state.signer
        return {
            "algorithm": "ed25519",
            "key_id": signer.key_id,
            "public_key": signer.public_key_b64(),
        }

    # The /verify router is wired in a later commit.
    from trust_api.api.routes import router as api_router

    app.include_router(api_router)

    logger.info("Trust API initialized (env=%s)", settings.environment)
    return app


# Uvicorn entrypoint: `uvicorn trust_api.main:app`
app = create_app()
