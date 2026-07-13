"""Ed25519 key management for proof signing (Week 6).

We use the `cryptography` library's Ed25519 primitives as-is (audited,
standard, tiny 32-byte keys / 64-byte signatures) — no home-grown crypto.

The signing key is loaded from PROOF_SIGNING_KEY (base64 of the 32-byte
private seed). If it's absent we generate an EPHEMERAL key and log a loud
warning — usable for local dev, never for production (proofs won't verify
across restarts and the key isn't backed by anything).
"""

from __future__ import annotations

import base64
import hashlib

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from trust_api.config import Settings
from trust_api.core.logging import get_logger

logger = get_logger(__name__)


class Signer:
    """Holds the process signing key and derived public identity."""

    def __init__(self, private_key: Ed25519PrivateKey, *, ephemeral: bool) -> None:
        self._private_key = private_key
        self.ephemeral = ephemeral
        self.public_bytes = private_key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        # Short, stable id derived from the public key — lets keys rotate.
        self.key_id = hashlib.sha256(self.public_bytes).hexdigest()[:16]

    def sign(self, message: bytes) -> bytes:
        return self._private_key.sign(message)

    def public_key_b64(self) -> str:
        return base64.b64encode(self.public_bytes).decode("ascii")


def load_signer(settings: Settings) -> Signer:
    """Build a Signer from settings; ephemeral (with a WARNING) if no key set."""
    raw = settings.proof_signing_key.strip()
    if raw:
        private_key = Ed25519PrivateKey.from_private_bytes(base64.b64decode(raw))
        return Signer(private_key, ephemeral=False)
    logger.warning(
        "PROOF_SIGNING_KEY is not set — generating an EPHEMERAL Ed25519 signing key. "
        "Proofs will not verify across restarts and this key is NOT for production."
    )
    return Signer(Ed25519PrivateKey.generate(), ephemeral=True)


def verify_signature(public_bytes: bytes, message: bytes, signature: bytes) -> bool:
    """Return True iff ``signature`` is a valid Ed25519 sig over ``message``."""
    try:
        Ed25519PublicKey.from_public_bytes(public_bytes).verify(signature, message)
        return True
    except InvalidSignature:
        return False
