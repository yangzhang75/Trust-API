"""Tests for the dashboard API-key gate."""

from __future__ import annotations

from trust_api.config import Settings
from trust_api.dashboard.auth import allowed_dashboard_keys, verify_dashboard_key


def test_regular_api_key_grants_access() -> None:
    s = Settings(api_keys="user-key")
    assert verify_dashboard_key(s, "user-key") is True


def test_dashboard_admin_key_grants_access() -> None:
    s = Settings(api_keys="user-key", dashboard_api_keys="admin-key")
    assert verify_dashboard_key(s, "admin-key") is True
    assert allowed_dashboard_keys(s) == {"user-key", "admin-key"}


def test_wrong_key_is_rejected() -> None:
    s = Settings(api_keys="user-key", dashboard_api_keys="admin-key")
    assert verify_dashboard_key(s, "nope") is False


def test_empty_key_is_rejected() -> None:
    s = Settings(api_keys="user-key")
    assert verify_dashboard_key(s, "") is False
    assert verify_dashboard_key(s, None) is False


def test_closed_when_no_keys_configured() -> None:
    s = Settings(api_keys="", dashboard_api_keys="")
    assert allowed_dashboard_keys(s) == set()
    assert verify_dashboard_key(s, "anything") is False
