"""Shared pytest fixtures.

Tests run against the app factory with a deterministic test Settings
instance so they never depend on the developer's local environment.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from trust_api.config import Settings
from trust_api.main import create_app

TEST_API_KEY = "test-key"


@pytest.fixture
def settings() -> Settings:
    """Settings with a known API key and rate limit for tests."""
    return Settings(
        api_keys=TEST_API_KEY,
        rate_limit_per_minute=1000,
        environment="test",
    )


@pytest.fixture
def client(settings: Settings) -> TestClient:
    """A TestClient bound to an app built from the test settings."""
    app = create_app(settings)
    return TestClient(app)
