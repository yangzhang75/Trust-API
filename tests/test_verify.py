"""Tests for POST /verify (deterministic Week 1 stub)."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock

from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from tests.conftest import TEST_API_KEY
from trust_api.config import Settings
from trust_api.db.models import Wallet
from trust_api.db.session import get_db
from trust_api.main import create_app
from trust_api.services.features import compute_features

VALID_WALLET = "0x52908400098527886E0F7030069857D2E4169EE7"
AUTH = {"X-API-Key": TEST_API_KEY}


def _db_client(db) -> TestClient:
    """A TestClient whose /verify reads from the given (real or mock) db."""
    app = create_app(
        Settings(api_keys=TEST_API_KEY, rate_limit_per_minute=1000, environment="test")
    )
    app.dependency_overrides[get_db] = lambda: db
    return TestClient(app)


def test_verify_returns_stub_assessment(client: TestClient) -> None:
    resp = client.post(
        "/verify", json={"wallet": VALID_WALLET, "chains": ["ethereum"]}, headers=AUTH
    )
    assert resp.status_code == 200

    body = resp.json()
    assert body["wallet"] == VALID_WALLET
    assert body["human_likelihood"] in {"high", "medium", "low"}
    assert body["trust_tier"] in {"bronze", "silver", "gold"}
    assert 0.0 <= body["confidence_score"] <= 1.0
    assert isinstance(body["risk_flags"], list)
    assert body["chains"] == ["ethereum"]

    proof = body["proof"]
    assert set(proof) == {"issued_at", "expires_at", "valid_for_hours", "signature"}
    assert proof["valid_for_hours"] >= 1
    assert proof["signature"].startswith("stub-")


def test_verify_is_deterministic(client: TestClient) -> None:
    payload = {"wallet": VALID_WALLET, "chains": ["ethereum"]}
    first = client.post("/verify", json=payload, headers=AUTH).json()
    second = client.post("/verify", json=payload, headers=AUTH).json()
    # Assessment fields are derived from the wallet hash, so they're stable.
    for field in ("human_likelihood", "trust_tier", "confidence_score", "risk_flags"):
        assert first[field] == second[field]


def test_verify_defaults_chains_to_ethereum(client: TestClient) -> None:
    resp = client.post("/verify", json={"wallet": VALID_WALLET}, headers=AUTH)
    assert resp.status_code == 200
    assert resp.json()["chains"] == ["ethereum"]


def test_verify_invalid_wallet_returns_400(client: TestClient) -> None:
    resp = client.post("/verify", json={"wallet": "0xnothex", "chains": ["ethereum"]}, headers=AUTH)
    assert resp.status_code == 400


def test_verify_malformed_body_returns_422(client: TestClient) -> None:
    resp = client.post("/verify", json={"chains": ["ethereum"]}, headers=AUTH)  # missing wallet
    assert resp.status_code == 422


def test_verify_missing_api_key_returns_401(client: TestClient) -> None:
    resp = client.post("/verify", json={"wallet": VALID_WALLET, "chains": ["ethereum"]})
    assert resp.status_code == 401


def test_verify_invalid_api_key_returns_401(client: TestClient) -> None:
    resp = client.post(
        "/verify",
        json={"wallet": VALID_WALLET, "chains": ["ethereum"]},
        headers={"X-API-Key": "wrong-key"},
    )
    assert resp.status_code == 401


# --- Week 3: stub-safe wiring of stored features into /verify ---


def test_verify_reads_stored_features_but_output_stays_stub(db_session: Session) -> None:
    w = Wallet(address=VALID_WALLET)
    db_session.add(w)
    db_session.flush()
    compute_features(db_session, w.id, now=datetime(2026, 1, 1, tzinfo=UTC))

    resp = _db_client(db_session).post("/verify", json={"wallet": VALID_WALLET}, headers=AUTH)
    assert resp.status_code == 200
    # Output is still the deterministic stub — reading features didn't change it.
    assert resp.json()["confidence_score"] == 0.6703


def test_verify_works_when_no_features_row(db_session: Session) -> None:
    resp = _db_client(db_session).post("/verify", json={"wallet": VALID_WALLET}, headers=AUTH)
    assert resp.status_code == 200


def test_verify_degrades_to_stub_on_db_error() -> None:
    broken = MagicMock()
    broken.execute.side_effect = SQLAlchemyError("db down")
    resp = _db_client(broken).post("/verify", json={"wallet": VALID_WALLET}, headers=AUTH)
    assert resp.status_code == 200  # DB failure must not break /verify
