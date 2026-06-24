"""Application configuration via pydantic-settings.

All runtime configuration is read from the environment (or a local .env
file). See .env.example for the full list of supported variables.
"""

from __future__ import annotations

from functools import lru_cache
from typing import ClassVar

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Typed application settings loaded from the environment."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- App ---
    app_name: str = "Proof-of-Human Trust API"
    environment: str = Field(default="development")
    log_level: str = Field(default="INFO")

    # --- Auth ---
    # Comma-separated allowlist of accepted API keys, e.g. "key1,key2".
    api_keys: str = Field(default="")

    # --- Rate limiting ---
    rate_limit_per_minute: int = Field(default=60, ge=1)

    # --- Data layer ---
    database_url: str = Field(default="postgresql+psycopg://trust:trust@localhost:5432/trust")
    redis_url: str = Field(default="redis://localhost:6379/0")

    # --- Proof issuance (stub config; real signing arrives later) ---
    proof_valid_for_hours: int = Field(default=24, ge=1)

    # Keys that must never guard a real deployment.
    WEAK_API_KEYS: ClassVar[set[str]] = {"", "dev-key", "test-key", "changeme", "secret"}

    @property
    def api_key_set(self) -> set[str]:
        """Parsed set of accepted API keys (empty if none configured)."""
        return {k.strip() for k in self.api_keys.split(",") if k.strip()}

    @property
    def is_production(self) -> bool:
        return self.environment.strip().lower() in {"production", "prod"}

    def validate_runtime(self) -> None:
        """Fail fast if production is misconfigured with weak/no API keys.

        Lets the dev default (`dev-key`) keep `docker compose up` working
        locally, while refusing to start a production process behind a
        known/empty key.
        """
        keys = self.api_key_set
        if self.is_production and (not keys or keys <= self.WEAK_API_KEYS):
            raise RuntimeError(
                "Refusing to start in production without strong API_KEYS "
                "configured (the dev default must be overridden)."
            )


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance (one per process)."""
    return Settings()
