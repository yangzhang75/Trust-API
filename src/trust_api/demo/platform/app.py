"""The mock platform FastAPI app (a client of the Trust API).

Scenario endpoints are added in later commits; this is the skeleton: settings,
the Trust API client on app.state, and a health check.
"""

from __future__ import annotations

from fastapi import FastAPI

from trust_api.demo.platform.client import TrustClient
from trust_api.demo.platform.config import MockSettings, get_mock_settings


def create_mock_app(settings: MockSettings | None = None) -> FastAPI:
    settings = settings or get_mock_settings()
    app = FastAPI(title="Mock Platform — Trust API client", version="0.1.0")
    app.state.settings = settings
    app.state.trust_client = TrustClient(settings.trust_api_url, settings.trust_api_key)

    @app.get("/mock/health", tags=["mock"])
    def health() -> dict:
        return {"status": "ok", "trust_api_url": settings.trust_api_url}

    return app
