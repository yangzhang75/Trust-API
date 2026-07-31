"""Tests for the mock platform app skeleton."""

from __future__ import annotations

from fastapi.testclient import TestClient

from trust_api.demo.platform.app import create_mock_app
from trust_api.demo.platform.config import MockSettings, get_mock_settings


def test_health_reports_trust_api_url() -> None:
    app = create_mock_app(MockSettings(trust_api_url="http://trust.test", trust_api_key="k"))
    resp = TestClient(app).get("/mock/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "trust_api_url": "http://trust.test"}


def test_get_mock_settings_returns_settings() -> None:
    assert isinstance(get_mock_settings(), MockSettings)


def test_create_mock_app_uses_default_settings() -> None:
    # Exercises the `settings or get_mock_settings()` default path.
    app = create_mock_app()
    assert TestClient(app).get("/mock/health").status_code == 200
