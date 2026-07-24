"""End-to-end integration across the proof-flow endpoints (Week 9).

Ties the pieces together as a third-party integrator would: generate a proof,
serialize it both ways, deserialize, and verify — through the real HTTP
endpoints and a real DB, including the revoke lifecycle. Unit-level behavior of
each part lives in test_proof_{generate,verify}_endpoint / _share / _offline."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tests.conftest import TEST_API_KEY
from trust_api.config import Settings
from trust_api.db.session import get_db
from trust_api.jobs.revoke import revoke_by_wallet
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


def test_happy_path_generate_serialize_deserialize_verify() -> None:
    """generate -> both wire forms -> deserialize -> verify -> valid."""
    client = _client()
    gen = client.post("/proof/generate", json={"wallet": VALID_WALLET}, headers=AUTH).json()

    # Both serializations deserialize to the same proof, and the encoded form
    # round-trips byte-stably across the HTTP boundary.
    from_encoded = decode_proof(gen["encoded"])
    assert from_encoded.payload == gen["payload"]
    assert encode_proof(from_encoded) == gen["encoded"]

    # Verify via the compact form.
    v1 = client.post("/proof/verify", json={"encoded": gen["encoded"]}, headers=AUTH).json()
    assert v1["valid"] is True and v1["reason"] == "ok"

    # Verify via the raw JSON form — same verdict.
    v2 = client.post(
        "/proof/verify",
        json={"payload": gen["payload"], "signature": gen["signature"]},
        headers=AUTH,
    ).json()
    assert v2["valid"] is True and v2["reason"] == "ok"
    assert v1["key_id"] == v2["key_id"] == gen["payload"]["key_id"]


def test_full_lifecycle_generate_verify_revoke_verify(db_session: Session) -> None:
    """A DB-backed lifecycle: valid until revoked, then reported revoked."""
    client = _client(db_session)
    gen = client.post("/proof/generate", json={"wallet": VALID_WALLET}, headers=AUTH).json()

    before = client.post("/proof/verify", json={"encoded": gen["encoded"]}, headers=AUTH).json()
    assert before["valid"] is True and before["revoked"] is False

    assert revoke_by_wallet(db_session, VALID_WALLET) == 1

    after = client.post("/proof/verify", json={"encoded": gen["encoded"]}, headers=AUTH).json()
    assert after["valid"] is False
    assert after["reason"] == "revoked"
    assert after["revoked"] is True
