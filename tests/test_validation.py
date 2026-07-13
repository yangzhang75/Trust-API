"""Tests for the shared wallet-address validator (H2 fix)."""

from __future__ import annotations

import pytest

from trust_api.core.validation import (
    InvalidWalletError,
    is_valid_evm_wallet,
    require_valid_wallet,
)

VALID = "0x52908400098527886E0F7030069857D2E4169EE7"


def test_is_valid_evm_wallet_accepts_canonical() -> None:
    assert is_valid_evm_wallet(VALID)


@pytest.mark.parametrize(
    "bad",
    ["0xdeadbeef", "not_an_address", "", VALID + "00", VALID[:-1], "0X" + VALID[2:]],
)
def test_is_valid_evm_wallet_rejects_malformed(bad: str) -> None:
    assert not is_valid_evm_wallet(bad)


def test_require_valid_wallet_passes_for_valid() -> None:
    require_valid_wallet(VALID)  # no raise


def test_require_valid_wallet_raises_for_invalid() -> None:
    with pytest.raises(InvalidWalletError):
        require_valid_wallet("0xdeadbeef")
