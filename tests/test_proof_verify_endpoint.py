"""Tests for POST /proof/verify (recheck a previously issued proof)."""

from __future__ import annotations

import base64

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tests.conftest import TEST_API_KEY
from trust_api.config import Settings
from trust_api.db.session import get_db
from trust_api.jobs.revoke import revoke_by_wallet
from trust_api.main import create_app

VALID_WALLET = "0x52908400098527886E0F7030069857D2E4169EE7"
AUTH = {"X-API-Key": TEST_API_KEY}


def _client(db=None) -> TestClient:
    app = create_app(
        Settings(api_keys=TEST_API_KEY, rate_limit_per_minute=1000, environment="test")
    )
    app.dependency_overrides[get_db] = lambda: db
    return TestClient(app)


def _issue(client: TestClient) -> dict:
    """Return a full /verify response body (the round-trip payload)."""
    return client.post(
        "/verify", json={"wallet": VALID_WALLET, "chains": ["ethereum"]}, headers=AUTH
    ).json()


def test_proof_verify_accepts_valid_proof() -> None:
    client = _client()
    issued = _issue(client)
    resp = client.post("/proof/verify", json=issued, headers=AUTH)
    assert resp.status_code == 200
    assert resp.json() == {
        "valid": True,
        "reason": "ok",
        "key_id": issued["proof"]["key_id"],
    }


def test_proof_verify_rejects_tampered_field() -> None:
    client = _client()
    issued = _issue(client)
    issued["trust_tier"] = "gold"  # not what was signed
    body = client.post("/proof/verify", json=issued, headers=AUTH).json()
    assert body["valid"] is False
    assert body["reason"] == "bad_signature"


def test_proof_verify_rejects_tampered_signature() -> None:
    client = _client()
    issued = _issue(client)
    raw = bytearray(base64.b64decode(issued["proof"]["signature"]))
    raw[0] ^= 0x01
    issued["proof"]["signature"] = base64.b64encode(bytes(raw)).decode("ascii")
    body = client.post("/proof/verify", json=issued, headers=AUTH).json()
    assert body["valid"] is False
    assert body["reason"] == "bad_signature"


def test_proof_verify_rejects_unknown_key() -> None:
    client = _client()
    issued = _issue(client)
    issued["proof"]["key_id"] = "deadbeefdeadbeef"
    body = client.post("/proof/verify", json=issued, headers=AUTH).json()
    assert body["valid"] is False
    assert body["reason"] == "unknown_key"
    assert body["key_id"] == "deadbeefdeadbeef"


def test_proof_verify_reports_revoked(db_session: Session) -> None:
    client = _client(db_session)
    issued = _issue(client)  # persisted via the same session
    assert revoke_by_wallet(db_session, VALID_WALLET) == 1
    body = client.post("/proof/verify", json=issued, headers=AUTH).json()
    assert body["valid"] is False
    assert body["reason"] == "revoked"


def test_proof_verify_requires_api_key() -> None:
    client = _client()
    issued = _issue(client)
    assert client.post("/proof/verify", json=issued).status_code == 401
