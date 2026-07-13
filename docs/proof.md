# Proof generation & verification (Week 6)

Every `POST /verify` response includes a **cryptographic proof**: an
Ed25519 signature over a canonical form of the assessment. The goal is that
a third party can verify a proof **offline** — using only the public key —
without ever calling this service back, and without the proof leaking any
raw wallet transaction data.

## What is signed

The signature covers exactly these 11 fields (the *payload*):

| Field | Type | Notes |
| --- | --- | --- |
| `wallet` | string | The assessed address, verbatim from the request |
| `human_likelihood` | string | `high` \| `medium` \| `low` |
| `trust_tier` | string | `bronze` \| `silver` \| `gold` |
| `confidence_score` | number | 0.0–1.0, rounded to 4 decimals |
| `risk_flags` | string[] | e.g. `["low_activity"]` |
| `chains` | string[] | e.g. `["ethereum"]` |
| `scorer_version` | string | e.g. `0.4.0-graph` |
| `key_id` | string | `sha256(public_key)[:16]`, hex — identifies the key |
| `issued_at` | string | ISO-8601 UTC, verbatim |
| `expires_at` | string | ISO-8601 UTC, verbatim |
| `nonce` | string | 32 hex chars, unique per proof |

There is **no raw transaction data** in the payload — only the assessment
outputs. This is a privacy invariant.

The `/verify` response returns the proof as:

```json
"proof": {
  "issued_at": "...", "expires_at": "...", "valid_for_hours": 24,
  "signature": "<base64>", "key_id": "...", "nonce": "...",
  "scorer_version": "0.4.0-graph"
}
```

`valid_for_hours` is convenience metadata (not signed); it equals the gap
between `issued_at` and `expires_at`. Everything else in `proof`, plus the
top-level `wallet`, `human_likelihood`, `trust_tier`, `confidence_score`,
`risk_flags`, and `chains`, is part of the signed payload.

## Canonical form (the single source of truth)

The signature is computed over the payload serialized as **canonical JSON**:

- keys sorted lexicographically (`sort_keys=True`),
- no insignificant whitespace (`separators=(",", ":")`),
- UTF-8 encoded, `ensure_ascii=False`.

A verifier reconstructs the payload dict from the response fields, serializes
it with the same rules, and checks the signature. Because `issued_at` /
`expires_at` are carried **verbatim** (the exact strings that were signed,
not re-serialized datetimes), the reconstructed bytes are identical.

### Cross-language caveat (flagged, not hidden)

Canonical JSON is only fully deterministic across languages if number
formatting matches. The one number in the payload is `confidence_score`. We
round it to 4 decimals upstream, which keeps Python's `json` output stable.
A non-Python verifier must reproduce the same number formatting (e.g.
`0.67` not `0.6700`). This is a well-known canonical-JSON concern; if strict
cross-language interop becomes a requirement, the correct fix is to sign the
score as a string, not a float. We did **not** invent a custom encoding — we
use the standard library's JSON as-is and document this edge.

## Verifying offline (only the public key needed)

Fetch the key once:

```bash
curl -s localhost:8000/proof/public-key
# {"algorithm":"ed25519","key_id":"9f86d081884c7d65","public_key":"<base64>"}
```

Then verify a `/verify` response body (`resp`) with nothing but the public
key:

```python
import base64, json
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.exceptions import InvalidSignature

def canonical_bytes(payload: dict) -> bytes:
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")

def verify(resp: dict, public_key_b64: str) -> bool:
    p = resp["proof"]
    payload = {
        "wallet": resp["wallet"],
        "human_likelihood": resp["human_likelihood"],
        "trust_tier": resp["trust_tier"],
        "confidence_score": resp["confidence_score"],
        "risk_flags": resp["risk_flags"],
        "chains": resp["chains"],
        "scorer_version": p["scorer_version"],
        "key_id": p["key_id"],
        "issued_at": p["issued_at"],
        "expires_at": p["expires_at"],
        "nonce": p["nonce"],
    }
    pub = Ed25519PublicKey.from_public_bytes(base64.b64decode(public_key_b64))
    try:
        pub.verify(base64.b64decode(p["signature"]), canonical_bytes(payload))
    except InvalidSignature:
        return False
    # Also enforce expiry (and confirm key_id matches the key you fetched).
    from datetime import datetime, timezone
    return datetime.now(timezone.utc) <= datetime.fromisoformat(p["expires_at"])
```

Expiry is enforced by comparing `now` against `expires_at`. Revocation
(below) is **not** visible offline — it requires our database.

## The `POST /proof/verify` endpoint

A convenience endpoint that runs the same check server-side and also
consults the revocation table. Submit a `/verify` response back to it:

```bash
curl -s -X POST localhost:8000/proof/verify \
  -H "Content-Type: application/json" -H "X-API-Key: dev-key" \
  -d @verify_response.json
# {"valid": true, "reason": "ok", "key_id": "9f86d081884c7d65"}
```

`reason` is one of:

| reason | meaning |
| --- | --- |
| `ok` | valid, unexpired, not revoked |
| `unknown_key` | `key_id` is not this server's current key |
| `bad_signature` | signature doesn't match the reconstructed payload |
| `revoked` | the proof was revoked (DB lookup) |
| `expired` | `now > expires_at` |

Check order is `unknown_key → bad_signature → revoked → expired → ok`.

## Signing keys

- Loaded from `PROOF_SIGNING_KEY` (base64 32-byte Ed25519 seed) **only** —
  never committed. See `.env.example`.
- If unset, the app generates an **ephemeral** key and logs a loud
  `WARNING`. Ephemeral keys change every restart, so previously issued
  proofs stop verifying. Never use ephemeral keys in production.
- `key_id = sha256(public_key)[:16]`. It is carried in every proof so
  consumers can pin a key and support rotation: stand up the new key,
  publish both public keys, then retire the old `key_id`.

Generate a dev key:

```bash
python -c "import base64,os; print(base64.b64encode(os.urandom(32)).decode())"
```

## Revocation

Proofs are persisted (payload + signature + `key_id`, never raw tx data) so
they can be revoked before expiry:

```bash
python -m trust_api.jobs.revoke --proof-id 42
python -m trust_api.jobs.revoke --wallet 0x52908400098527886E0F7030069857D2E4169EE7
```

Revocation flips a `revoked` flag; `POST /proof/verify` (and
`ProofService.verify` with a DB session) then returns `reason="revoked"`.
Persistence is best-effort at issue time: if the DB is unavailable, the
proof is still returned and is cryptographically valid, but a `WARNING` is
logged noting it is **not revocable**.

## Honesty notes

- We use the `cryptography` library's Ed25519 primitives directly — no
  home-grown signature scheme.
- The float-canonicalization caveat above is a real cross-language edge and
  is documented rather than papered over.
- The ephemeral dev key warns loudly; a silent ephemeral key would be a
  security landmine.
