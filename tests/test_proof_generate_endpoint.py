"""Tests for POST /proof/generate (issue a self-contained, shareable proof)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.conftest import TEST_API_KEY
from trust_api.config import Settings
from trust_api.db.session import get_db
from trust_api.main import create_app
from trust_api.services.proof.share import decode_proof, encode_proof

VALID_WALLET = "0x52908400098527886E0F7030069857D2E4169EE7"
AUTH = {"X-API-Key": TEST_API_KEY}


def _client(db=None) -> TestClient:
    app = create_app(
        Settings(api_keys=TEST_API_KEY, rate_limit_per_minute=1000, environment="test")
    )
    app.dependency_overrides[get_db] = lambda: db
    return TestClient(app)


def test_generate_returns_self_contained_proof() -> None:
    client = _client()
    resp = client.post(
        "/proof/generate", json={"wallet": VALID_WALLET, "chains": ["ethereum"]}, headers=AUTH
    )
    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == {"payload", "signature", "encoded", "summary"}
    assert body["payload"]["wallet"] == VALID_WALLET
    assert body["payload"]["chains"] == ["ethereum"]
    assert VALID_WALLET in body["summary"]


def test_generate_encoded_form_decodes_to_the_same_payload() -> None:
    client = _client()
    body = client.post("/proof/generate", json={"wallet": VALID_WALLET}, headers=AUTH).json()
    proof = decode_proof(body["encoded"])
    assert proof.payload == body["payload"]
    assert proof.signature == body["signature"]
    # And the server's encoded form is exactly what re-encoding produces.
    assert encode_proof(proof) == body["encoded"]


def test_generate_rejects_invalid_wallet() -> None:
    client = _client()
    resp = client.post("/proof/generate", json={"wallet": "0xnothex"}, headers=AUTH)
    assert resp.status_code == 400


def test_generate_requires_api_key() -> None:
    client = _client()
    assert client.post("/proof/generate", json={"wallet": VALID_WALLET}).status_code == 401
