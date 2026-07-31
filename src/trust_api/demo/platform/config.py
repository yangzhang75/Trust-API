"""Configuration for the mock platform (its own env, not the Trust API's)."""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class MockSettings(BaseSettings):
    """Where the mock finds the Trust API and its own local metrics DB.

    Read from ``MOCK_*`` env vars (e.g. ``MOCK_TRUST_API_URL``). Defaults suit
    the local docker-compose stack on remapped host ports.
    """

    model_config = SettingsConfigDict(env_prefix="MOCK_", env_file=".env", extra="ignore")

    # Base URL of the Trust API we consume (public interface only).
    trust_api_url: str = "http://localhost:18000"
    # A real API key from the Trust API's allowlist.
    trust_api_key: str = "dev-key"
    # Local SQLite metrics store — deliberately NOT the Trust API's Postgres.
    db_path: str = "mock_metrics.db"


def get_mock_settings() -> MockSettings:
    return MockSettings()
