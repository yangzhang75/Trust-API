"""Shared wallet-address validation.

Single source of truth for the accepted address format. Used by the API
(`/verify`) and by every scoring/ingestion entry point (batch, CLI, worker,
refresh-stale) so a malformed address is rejected consistently instead of
being silently ingested and scored.
"""

from __future__ import annotations

import re

# EVM address: 0x followed by 40 hex chars. (Non-EVM chains would add their
# own pattern here.)
EVM_WALLET_REGEX = re.compile(r"^0x[a-fA-F0-9]{40}$")


class InvalidWalletError(ValueError):
    """Raised when a wallet address is not a syntactically valid EVM address."""


def is_valid_evm_wallet(wallet: str) -> bool:
    """Return True if ``wallet`` is a syntactically valid EVM address."""
    return bool(EVM_WALLET_REGEX.match(wallet))


def require_valid_wallet(wallet: str) -> None:
    """Raise :class:`InvalidWalletError` if ``wallet`` is not a valid address."""
    if not is_valid_evm_wallet(wallet):
        raise InvalidWalletError(f"invalid EVM wallet address: {wallet!r}")
