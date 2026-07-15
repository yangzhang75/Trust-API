"""Tests for POST /verify (real scoring + Ed25519-signed proof)."""

from __future__ import annotations

import base64
from unittest.mock import MagicMock

import httpx
import respx
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from tests.conftest import TEST_API_KEY
from trust_api.config import Settings
from trust_api.db.models import Wallet, WalletFeature
from trust_api.db.session import get_db
from trust_api.main import create_app
from trust_api.services.proof.canonical import build_payload, canonical_bytes
from trust_api.services.proof.keys import verify_signature

VALID_WALLET = "0x52908400098527886E0F7030069857D2E4169EE7"
AUTH = {"X-API-Key": TEST_API_KEY}
PROVIDER_BASE = "https://api.etherscan.io/v2/api"


def _db_client(db) -> TestClient:
    """A TestClient whose /verify reads from the given (real or mock) db."""
    app = create_app(
        Settings(api_keys=TEST_API_KEY, rate_limit_per_minute=1000, environment="test")
    )
    app.dependency_overrides[get_db] = lambda: db
    return TestClient(app)


def test_verify_returns_signed_assessment(client: TestClient) -> None:
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
    assert set(proof) == {
        "issued_at",
        "expires_at",
        "valid_for_hours",
        "signature",
        "key_id",
        "nonce",
        "scorer_version",
    }
    assert proof["valid_for_hours"] >= 1
    assert len(base64.b64decode(proof["signature"])) == 64  # real Ed25519 sig


def test_verify_proof_is_third_party_verifiable(client: TestClient) -> None:
    """A verifier reconstructs the canonical payload from the response and
    checks the signature using only the public key — no callback needed."""
    body = client.post(
        "/verify", json={"wallet": VALID_WALLET, "chains": ["ethereum"]}, headers=AUTH
    ).json()
    proof = body["proof"]

    pub = client.get("/proof/public-key").json()
    assert pub["key_id"] == proof["key_id"]
    public_bytes = base64.b64decode(pub["public_key"])

    payload = build_payload(
        wallet=body["wallet"],
        human_likelihood=body["human_likelihood"],
        trust_tier=body["trust_tier"],
        confidence_score=body["confidence_score"],
        risk_flags=body["risk_flags"],
        chains=body["chains"],
        scorer_version=proof["scorer_version"],
        key_id=proof["key_id"],
        issued_at=proof["issued_at"],
        expires_at=proof["expires_at"],
        nonce=proof["nonce"],
    )
    sig = base64.b64decode(proof["signature"])
    assert verify_signature(public_bytes, canonical_bytes(payload), sig) is True

    # A single-byte tamper of the payload must fail verification.
    tampered = dict(payload, human_likelihood="high")
    assert verify_signature(public_bytes, canonical_bytes(tampered), sig) is False


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


# --- Week 4: real scoring wired into /verify (contract unchanged) ---


def test_verify_scores_high_for_strong_stored_features(db_session: Session) -> None:
    w = Wallet(address=VALID_WALLET)
    db_session.add(w)
    db_session.flush()
    db_session.add(
        WalletFeature(
            wallet_id=w.id,
            chain="ethereum",
            payload={},
            wallet_age_days=800,
            tx_count=500,
            active_days=120,
            tx_per_active_day=4.0,
            counterparty_count=300,
            counterparty_diversity_ratio=0.6,
            inbound_ratio=0.5,
            burst_score=3,
            dormancy_flag=False,
            recency_days=1,
        )
    )
    db_session.commit()

    body = (
        _db_client(db_session).post("/verify", json={"wallet": VALID_WALLET}, headers=AUTH).json()
    )
    assert body["human_likelihood"] == "high"
    assert body["trust_tier"] == "gold"
    assert body["risk_flags"] == []


def test_verify_scores_low_when_no_data(db_session: Session) -> None:
    # No features row, no provider configured -> neutral features -> low trust.
    body = (
        _db_client(db_session).post("/verify", json={"wallet": VALID_WALLET}, headers=AUTH).json()
    )
    assert body["human_likelihood"] == "low"
    assert body["trust_tier"] == "bronze"


def test_verify_degrades_to_neutral_on_db_error() -> None:
    broken = MagicMock()
    broken.execute.side_effect = SQLAlchemyError("db down")
    resp = _db_client(broken).post("/verify", json={"wallet": VALID_WALLET}, headers=AUTH)
    assert resp.status_code == 200  # DB failure must not break /verify
    assert resp.json()["human_likelihood"] == "low"


@respx.mock
def test_verify_ingests_on_miss_when_provider_configured(db_session: Session) -> None:
    raw = {
        "hash": "0x" + "e" * 64,
        "from": VALID_WALLET.lower(),
        "to": "0x000000000000000000000000000000000000dead",
        "value": "1",
        "timeStamp": "1700000000",
        "blockNumber": "18000000",
        "contractAddress": "",
    }
    respx.get(PROVIDER_BASE).mock(
        return_value=httpx.Response(200, json={"status": "1", "message": "OK", "result": [raw]})
    )
    app = create_app(
        Settings(
            api_keys=TEST_API_KEY,
            rate_limit_per_minute=1000,
            environment="test",
            etherscan_api_key="k",
            etherscan_base_url=PROVIDER_BASE,
            ingestion_backoff_seconds=0,
            ingestion_cache_ttl_seconds=0,
        )
    )
    app.dependency_overrides[get_db] = lambda: db_session
    resp = TestClient(app).post("/verify", json={"wallet": VALID_WALLET}, headers=AUTH)
    assert resp.status_code == 200
    # Features were ingested + computed on demand.
    assert db_session.execute(select(WalletFeature)).scalars().all()
