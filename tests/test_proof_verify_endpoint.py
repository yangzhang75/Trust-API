"""Tests for POST /proof/verify (verify a self-contained proof).

The endpoint accepts the proof produced by /proof/generate in either wire
form — compact ``{"encoded": ...}`` or raw ``{"payload": ..., "signature": ...}``
— and returns {valid, reason, key_id, expires_at, revoked, summary}."""

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


def _generate(client: TestClient) -> dict:
    """Issue a fresh self-contained proof via /proof/generate."""
    return client.post(
        "/proof/generate", json={"wallet": VALID_WALLET, "chains": ["ethereum"]}, headers=AUTH
    ).json()


def test_verify_accepts_valid_proof_encoded_form() -> None:
    client = _client()
    issued = _generate(client)
    resp = client.post("/proof/verify", json={"encoded": issued["encoded"]}, headers=AUTH)
    assert resp.status_code == 200
    body = resp.json()
    assert body["valid"] is True
    assert body["reason"] == "ok"
    assert body["key_id"] == issued["payload"]["key_id"]
    assert body["expires_at"] == issued["payload"]["expires_at"]
    assert body["revoked"] is False
    assert VALID_WALLET in body["summary"]


def test_verify_accepts_valid_proof_raw_json_form() -> None:
    client = _client()
    issued = _generate(client)
    resp = client.post(
        "/proof/verify",
        json={"payload": issued["payload"], "signature": issued["signature"]},
        headers=AUTH,
    )
    assert resp.status_code == 200
    assert resp.json()["valid"] is True
    assert resp.json()["reason"] == "ok"


def test_verify_rejects_tampered_field() -> None:
    client = _client()
    issued = _generate(client)
    issued["payload"]["trust_tier"] = "gold"  # not what was signed
    body = client.post(
        "/proof/verify",
        json={"payload": issued["payload"], "signature": issued["signature"]},
        headers=AUTH,
    ).json()
    assert body["valid"] is False
    assert body["reason"] == "bad_signature"


def test_verify_rejects_tampered_signature() -> None:
    client = _client()
    issued = _generate(client)
    raw = bytearray(base64.b64decode(issued["signature"]))
    raw[0] ^= 0x01
    issued["signature"] = base64.b64encode(bytes(raw)).decode("ascii")
    body = client.post(
        "/proof/verify",
        json={"payload": issued["payload"], "signature": issued["signature"]},
        headers=AUTH,
    ).json()
    assert body["valid"] is False
    assert body["reason"] == "bad_signature"


def test_verify_rejects_unknown_key() -> None:
    client = _client()
    issued = _generate(client)
    issued["payload"]["key_id"] = "deadbeefdeadbeef"
    body = client.post(
        "/proof/verify",
        json={"payload": issued["payload"], "signature": issued["signature"]},
        headers=AUTH,
    ).json()
    assert body["valid"] is False
    assert body["reason"] == "unknown_key"
    assert body["key_id"] == "deadbeefdeadbeef"


def test_verify_reports_revoked(db_session: Session) -> None:
    client = _client(db_session)
    issued = _generate(client)  # persisted via the same session
    assert revoke_by_wallet(db_session, VALID_WALLET) == 1
    body = client.post("/proof/verify", json={"encoded": issued["encoded"]}, headers=AUTH).json()
    assert body["valid"] is False
    assert body["reason"] == "revoked"
    assert body["revoked"] is True


def test_verify_rejects_malformed_encoded() -> None:
    client = _client()
    resp = client.post("/proof/verify", json={"encoded": "!!! not base64 !!!"}, headers=AUTH)
    assert resp.status_code == 422
    assert "Malformed encoded proof" in resp.json()["detail"]


def test_verify_rejects_incomplete_request() -> None:
    client = _client()
    # neither an encoded string nor a complete payload+signature pair
    resp = client.post("/proof/verify", json={"payload": {"wallet": "x"}}, headers=AUTH)
    assert resp.status_code == 422
    assert "either 'encoded'" in resp.json()["detail"]


def test_verify_requires_api_key() -> None:
    client = _client()
    issued = _generate(client)
    assert client.post("/proof/verify", json={"encoded": issued["encoded"]}).status_code == 401
