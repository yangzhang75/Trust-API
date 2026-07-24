"""End-to-end proof-flow demo (Week 9).

Runnable::

    python -m trust_api.demo.proof_flow

The script IS the demo: it walks the full journey with visible, step-by-step
output —

  1. Alice generates a proof for her wallet.
  2. Alice serializes it two ways: raw JSON and a compact URL/QR form.
  3. Bob verifies it OFFLINE with only the public key — no server call.
  4. Bob also verifies it via POST /proof/verify (the server path).

— then demonstrates all four failure modes: expired, tampered, revoked, and
wrong key.

``run()`` holds the whole flow and takes its infrastructure as parameters so
it is fully unit-tested (see tests/test_proof_flow_demo.py). ``main()`` only
wires the real signer / DB / HTTP client, so it is excluded from coverage.
No new crypto — every check reuses the Week-6 primitives (verify_offline /
ProofService).
"""

from __future__ import annotations

import copy
import json
import os
import urllib.error
import urllib.request
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from trust_api.config import get_settings
from trust_api.db.session import get_sessionmaker
from trust_api.jobs.revoke import revoke_by_wallet
from trust_api.services.features import EMPTY_FEATURES
from trust_api.services.proof import ProofService, Signer, load_signer, verify_offline
from trust_api.services.proof.models import Proof
from trust_api.services.proof.share import decode_proof, encode_proof, proof_to_json
from trust_api.services.scoring import score

# Alice's wallet (a valid EVM checksum address). The demo is about the proof
# journey, not the score, so we score neutral features deterministically.
ALICE_WALLET = "0x52908400098527886E0F7030069857D2E4169EE7"
TTL_HOURS = 24

ServerVerify = Callable[[str], dict[str, Any]]


def _banner(out: Callable[[str], None], title: str) -> None:
    out("")
    out("=" * 70)
    out(f"  {title}")
    out("=" * 70)


def _show_result(out: Callable[[str], None], label: str, result: Any) -> None:
    out(f"  {label}: valid={result.valid!r} reason={result.reason!r}")


def run(
    *,
    signer: Signer,
    session: Any,
    server_verify: ServerVerify,
    wrong_public_key_b64: str,
    out: Callable[[str], None] = print,
) -> dict[str, Any]:
    """Walk the full proof journey. Returns a structured summary of outcomes.

    ``signer`` is the issuer key (Trust API); ``session`` a live DB session
    (used to persist the proof and, later, revoke it); ``server_verify(encoded)``
    performs the POST /proof/verify server path; ``wrong_public_key_b64`` is an
    unrelated public key for the wrong-key failure mode.
    """
    public_key = signer.public_key_b64()
    service = ProofService(signer, TTL_HOURS)

    # --- 1. Alice generates a proof for her wallet -----------------------
    _banner(out, "1. Alice generates a proof for her wallet")
    result = score(EMPTY_FEATURES)
    proof = service.generate(
        wallet=ALICE_WALLET, result=result, chains=["ethereum"], session=session
    )
    out(f"  wallet     : {ALICE_WALLET}")
    out(f"  key_id     : {proof.key_id}")
    out(f"  expires_at : {proof.expires_at}")
    out(f"  assessment : {result.human_likelihood.value} / {result.trust_tier.value}")

    # --- 2. Alice serializes it two ways ---------------------------------
    _banner(out, "2. Alice shares the proof (two interchangeable forms)")
    raw = proof_to_json(proof)
    compact = encode_proof(proof)
    out(f"  raw JSON   ({len(raw)} bytes): {raw[:72]}…")
    out(f"  compact    ({len(compact)} chars, URL/QR-safe): {compact[:72]}…")
    out(f"  offline verify URL: https://verify.example/p/{compact[:24]}…")

    # --- 3. Bob verifies OFFLINE with only the public key ----------------
    _banner(out, "3. Bob verifies OFFLINE — public key only, no server call")
    received = decode_proof(compact)  # Bob decodes what he received
    out(f"  Bob fetched the issuer public key: {public_key}")
    offline = verify_offline(public_key, received)
    _show_result(out, "offline verification", offline)
    out("  → Bob trusted the assessment without ever calling our server.")

    # --- 4. Bob also verifies via the server -----------------------------
    _banner(out, "4. Bob verifies via POST /proof/verify (server path)")
    server = server_verify(compact)
    out(f"  server response: {json.dumps(server)}")

    # --- Failure modes ---------------------------------------------------
    _banner(out, "FAILURE MODES (each must be detected)")

    # Expired: fast-forward past the signed expiry.
    expired_at = datetime.fromisoformat(proof.expires_at) + timedelta(seconds=1)
    expired = verify_offline(public_key, received, now=expired_at)
    _show_result(out, "expired  (verify 1s after expiry)", expired)

    # Tampered: mutate a signed field; the signature no longer matches. Pick a
    # tier that is genuinely different from the real one so the tamper is real.
    tampered_payload = copy.deepcopy(proof.payload)
    original_tier = tampered_payload["trust_tier"]
    tampered_payload["trust_tier"] = "gold" if original_tier != "gold" else "bronze"
    tampered = verify_offline(
        public_key, Proof(payload=tampered_payload, signature=proof.signature)
    )
    _show_result(
        out, f"tampered (trust_tier {original_tier} -> {tampered_payload['trust_tier']})", tampered
    )

    # Revoked: revoke via the CLI helper, then re-verify against the server.
    # NOTE offline verification cannot see revocation (it needs the issuer DB).
    revoked_count = revoke_by_wallet(session, ALICE_WALLET)
    out(f"  revoked {revoked_count} proof(s) for {ALICE_WALLET} via revoke_by_wallet")
    revoked_server = server_verify(compact)
    out(f"  server after revoke: {json.dumps(revoked_server)}")
    revoked_offline = verify_offline(public_key, received)
    _show_result(out, "revoked  (offline, cannot see revocation)", revoked_offline)
    out("  → revocation is enforced by the SERVER path, not offline.")

    # Wrong key: verify against an unrelated public key.
    wrong = verify_offline(wrong_public_key_b64, received)
    _show_result(out, "wrong key (verify with a different pubkey)", wrong)

    _banner(out, "DONE — happy path verified offline + on server; all failures detected")
    return {
        "offline_ok": offline,
        "server_ok": server,
        "expired": expired,
        "tampered": tampered,
        "revoked_server": revoked_server,
        "revoked_offline": revoked_offline,
        "wrong_key": wrong,
    }


def _http_server_verify(api_url: str, api_key: str) -> ServerVerify:  # pragma: no cover
    """A server_verify that POSTs to a running API (used by main())."""

    def _verify(encoded: str) -> dict[str, Any]:
        request = urllib.request.Request(
            f"{api_url}/proof/verify",
            data=json.dumps({"encoded": encoded}).encode("utf-8"),
            headers={"Content-Type": "application/json", "X-API-Key": api_key},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=5) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:  # server answered with a non-2xx
            body = exc.read().decode("utf-8", "replace")
            return {"valid": None, "reason": f"(HTTP {exc.code}: {body})"}
        except (urllib.error.URLError, OSError) as exc:  # could not reach the server
            return {"valid": None, "reason": f"(server unreachable: {exc})"}

    return _verify


def main() -> None:  # pragma: no cover
    settings = get_settings()
    signer = load_signer(settings)
    wrong = Signer(Ed25519PrivateKey.generate(), ephemeral=True)
    api_url = os.environ.get("API_URL", "http://localhost:18000")
    api_key = next(iter(settings.api_key_set), "")
    session = get_sessionmaker()()
    try:
        run(
            signer=signer,
            session=session,
            server_verify=_http_server_verify(api_url, api_key),
            wrong_public_key_b64=wrong.public_key_b64(),
        )
    finally:
        session.close()


if __name__ == "__main__":  # pragma: no cover
    main()
