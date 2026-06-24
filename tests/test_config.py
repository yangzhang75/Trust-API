"""Tests for settings parsing and the production runtime guard."""

from __future__ import annotations

import pytest

from trust_api.config import Settings
from trust_api.main import create_app


def test_api_key_set_parses_csv() -> None:
    s = Settings(api_keys=" k1 , k2 ,, k3 ")
    assert s.api_key_set == {"k1", "k2", "k3"}


def test_validate_runtime_allows_dev_default_in_development() -> None:
    # No exception: dev default is fine outside production.
    Settings(environment="development", api_keys="dev-key").validate_runtime()


def test_validate_runtime_rejects_weak_keys_in_production() -> None:
    with pytest.raises(RuntimeError):
        Settings(environment="production", api_keys="dev-key").validate_runtime()


def test_validate_runtime_rejects_empty_keys_in_production() -> None:
    with pytest.raises(RuntimeError):
        Settings(environment="prod", api_keys="").validate_runtime()


def test_validate_runtime_accepts_strong_key_in_production() -> None:
    Settings(environment="production", api_keys="a-strong-random-key").validate_runtime()


def test_create_app_raises_on_weak_production_config() -> None:
    with pytest.raises(RuntimeError):
        create_app(Settings(environment="production", api_keys="dev-key"))
