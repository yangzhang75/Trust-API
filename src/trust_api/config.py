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

    # --- Ingestion (Week 2) ---
    # Etherscan V2 unified API; one key works across chains via chainid.
    etherscan_api_key: str = Field(default="")
    etherscan_base_url: str = Field(default="https://api.etherscan.io/v2/api")
    # Per-request HTTP timeout (seconds) for provider calls.
    ingestion_timeout_seconds: float = Field(default=10.0, gt=0)
    # Total attempts (1 = no retry) for transient provider failures.
    ingestion_max_attempts: int = Field(default=4, ge=1)
    # Exponential-backoff base (seconds) between retries; 0 disables waiting.
    ingestion_backoff_seconds: float = Field(default=0.5, ge=0)
    # Max normalized transactions fetched per wallet.
    ingestion_max_transactions: int = Field(default=1000, ge=1)
    # Redis TTL (seconds) for cached wallet history; 0 disables caching.
    ingestion_cache_ttl_seconds: int = Field(default=21600, ge=0)
    # Background worker refresh interval (seconds).
    worker_interval_seconds: int = Field(default=3600, ge=1)
    # Re-score wallets whose latest score is older than this many hours.
    worker_stale_hours: int = Field(default=24, ge=1)

    @property
    def ingestion_provider_configured(self) -> bool:
        """True when a live provider key is set; otherwise callers stub."""
        return bool(self.etherscan_api_key.strip())

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
