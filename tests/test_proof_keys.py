"""Tests for Ed25519 proof key management + /proof/public-key."""

from __future__ import annotations

import base64
import logging

from fastapi.testclient import TestClient

from trust_api.config import Settings
from trust_api.services.proof.keys import load_signer, verify_signature

# A fixed 32-byte seed (base64) for deterministic tests — NOT a real key.
TEST_KEY_B64 = base64.b64encode(b"0" * 32).decode("ascii")


def test_load_signer_from_env_is_stable() -> None:
    s1 = load_signer(Settings(proof_signing_key=TEST_KEY_B64))
    s2 = load_signer(Settings(proof_signing_key=TEST_KEY_B64))
    assert s1.ephemeral is False
    assert s1.key_id == s2.key_id  # same key -> same key_id
    assert len(base64.b64decode(s1.public_key_b64())) == 32


def test_sign_and_verify_round_trip() -> None:
    signer = load_signer(Settings(proof_signing_key=TEST_KEY_B64))
    msg = b"canonical-payload-bytes"
    sig = signer.sign(msg)
    assert verify_signature(signer.public_bytes, msg, sig) is True
    assert verify_signature(signer.public_bytes, b"tampered", sig) is False


def test_ephemeral_key_warns(caplog) -> None:
    with caplog.at_level(logging.WARNING):
        signer = load_signer(Settings(proof_signing_key=""))
    assert signer.ephemeral is True
    assert any("EPHEMERAL" in r.message for r in caplog.records)


def test_public_key_endpoint(client: TestClient) -> None:
    resp = client.get("/proof/public-key")
    assert resp.status_code == 200
    body = resp.json()
    assert body["algorithm"] == "ed25519"
    assert body["key_id"] and len(base64.b64decode(body["public_key"])) == 32
