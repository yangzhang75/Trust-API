"""Test the end-to-end proof-flow demo (trust_api.demo.proof_flow.run).

Drives run() with a fixed issuer key, a real DB session, and a TestClient-backed
server_verify, asserting the happy path and every failure mode. The server app
uses the SAME signing key so the server verdict matches the offline one."""

from __future__ import annotations

import base64
import io
import urllib.error

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tests.conftest import TEST_API_KEY
from trust_api.config import Settings
from trust_api.db.session import get_db
from trust_api.demo.proof_flow import ALICE_WALLET, _http_server_verify, run
from trust_api.main import create_app
from trust_api.services.proof import load_signer

KEY_B64 = base64.b64encode(b"0" * 32).decode()
OTHER_KEY_B64 = base64.b64encode(b"1" * 32).decode()


def _server_verify(db_session: Session):
    """A server_verify bound to a TestClient that shares the test DB session and
    the same signing key as the demo's issuer."""
    app = create_app(
        Settings(
            api_keys=TEST_API_KEY,
            rate_limit_per_minute=1000,
            environment="test",
            proof_signing_key=KEY_B64,
        )
    )
    app.dependency_overrides[get_db] = lambda: db_session
    client = TestClient(app)

    def verify(encoded: str) -> dict:
        return client.post(
            "/proof/verify", json={"encoded": encoded}, headers={"X-API-Key": TEST_API_KEY}
        ).json()

    return verify


def test_proof_flow_demo_runs_end_to_end(db_session: Session) -> None:
    signer = load_signer(Settings(proof_signing_key=KEY_B64))
    wrong_pubkey = load_signer(Settings(proof_signing_key=OTHER_KEY_B64)).public_key_b64()
    lines: list[str] = []

    summary = run(
        signer=signer,
        session=db_session,
        server_verify=_server_verify(db_session),
        wrong_public_key_b64=wrong_pubkey,
        out=lines.append,
    )

    # Happy path: verifies offline and on the server.
    assert summary["offline_ok"].valid is True
    assert summary["server_ok"]["valid"] is True
    assert summary["server_ok"]["reason"] == "ok"

    # All four failure modes are detected with the right reason.
    assert summary["expired"].reason == "expired"
    assert summary["tampered"].reason == "bad_signature"
    assert summary["revoked_server"]["reason"] == "revoked"
    assert summary["wrong_key"].reason == "unknown_key"
    # Offline verification cannot see revocation — that's enforced server-side.
    assert summary["revoked_offline"].reason == "ok"

    # The script printed a visible, human-readable walkthrough.
    text = "\n".join(lines)
    assert ALICE_WALLET in text
    assert "Alice generates a proof" in text
    assert "Bob verifies OFFLINE" in text
    assert "FAILURE MODES" in text


class _FakeResp:
    """Minimal context-manager stand-in for urlopen's return value."""

    def __init__(self, body: bytes) -> None:
        self._body = body

    def __enter__(self) -> _FakeResp:
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    def read(self) -> bytes:
        return self._body


def test_http_server_verify_success(monkeypatch) -> None:
    verify = _http_server_verify("http://api.test", "k")
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda req, timeout=5: _FakeResp(b'{"valid": true, "reason": "ok"}'),
    )
    assert verify("ENCODED") == {"valid": True, "reason": "ok"}


def test_http_server_verify_reports_http_error(monkeypatch) -> None:
    verify = _http_server_verify("http://api.test", "k")

    def _raise(req, timeout=5):
        raise urllib.error.HTTPError(
            "http://api.test", 422, "Unprocessable", {}, io.BytesIO(b"bad request body")
        )

    monkeypatch.setattr("urllib.request.urlopen", _raise)
    out = verify("ENCODED")
    assert out["valid"] is None
    assert "HTTP 422" in out["reason"]
    assert "bad request body" in out["reason"]


def test_http_server_verify_reports_unreachable(monkeypatch) -> None:
    verify = _http_server_verify("http://api.test", "k")

    def _raise(req, timeout=5):
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr("urllib.request.urlopen", _raise)
    out = verify("ENCODED")
    assert out["valid"] is None
    assert "server unreachable" in out["reason"]
