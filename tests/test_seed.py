"""Tests for the labeled dataset and the seed routine."""

from __future__ import annotations

import sys
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from trust_api.config import Settings
from trust_api.db.models import Wallet
from trust_api.schemas.verify import Chain, is_valid_evm_wallet

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from seed_wallets import load_dataset, seed  # noqa: E402

VALID_LABELS = {"human", "sybil"}


def test_dataset_is_well_formed() -> None:
    wallets = load_dataset()
    assert len(wallets) >= 60  # expanded to >= 30 human + 30 sybil
    for entry in wallets:
        assert is_valid_evm_wallet(entry["address"]), entry["address"]
        assert entry["label"] in VALID_LABELS
        assert entry["note"].strip()
        assert "label_basis" in entry
        assert entry["label_source"].startswith("http")  # every label cites a source
        assert entry["chains"]  # non-empty chain list
    labels = {e["label"] for e in wallets}
    assert labels == VALID_LABELS


def test_dataset_is_balanced_and_unique() -> None:
    wallets = load_dataset()
    addresses = [w["address"] for w in wallets]
    assert len(addresses) == len(set(addresses))  # no duplicates / class overlap
    assert sum(w["label"] == "human" for w in wallets) >= 30
    assert sum(w["label"] == "sybil" for w in wallets) >= 30


def test_seed_registers_wallets_without_provider(db_session: Session) -> None:
    wallets = load_dataset()
    settings = Settings(etherscan_api_key="")  # no provider configured

    results = seed(db_session, wallets, settings)

    # No tx history fetched (no key), but every wallet row is registered.
    assert all(v is None for v in results.values())
    count = db_session.execute(select(func.count(Wallet.id))).scalar_one()
    assert count == len(wallets)


def test_seed_is_idempotent(db_session: Session) -> None:
    wallets = load_dataset()
    settings = Settings(etherscan_api_key="")
    seed(db_session, wallets, settings)
    seed(db_session, wallets, settings)  # second run must not duplicate wallet rows
    count = db_session.execute(select(func.count(Wallet.id))).scalar_one()
    assert count == len(wallets)


def test_dataset_chain_values_are_supported() -> None:
    for entry in load_dataset():
        for chain in entry["chains"]:
            assert Chain(chain) in (Chain.ethereum, Chain.arbitrum)
