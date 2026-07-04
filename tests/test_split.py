"""Tests for the deterministic, committed train/test split."""

from __future__ import annotations

from trust_api.jobs import split


def test_split_is_deterministic() -> None:
    wallets = split.load_dataset()
    assert split.build_split(wallets) == split.build_split(wallets)


def test_committed_split_matches_regeneration() -> None:
    # The committed file must equal what the code regenerates (no drift).
    regenerated = split.build_split(split.load_dataset())
    committed = split.load_split()
    assert committed["train"] == regenerated["train"]
    assert committed["test"] == regenerated["test"]


def test_no_wallet_in_both_splits() -> None:
    train, test = split.split_sets()
    assert train and test
    assert train.isdisjoint(test)


def test_split_covers_all_wallets_once() -> None:
    train, test = split.split_sets()
    addresses = {w["address"].lower() for w in split.load_dataset()}
    assert train | test == addresses
    assert len(train) + len(test) == len(addresses)


def test_split_is_stratified_and_roughly_70_30() -> None:
    train, test = split.split_sets()
    labels = {w["address"].lower(): w["label"] for w in split.load_dataset()}
    for s in (train, test):
        assert any(labels[a] == "human" for a in s)  # both classes present
        assert any(labels[a] == "sybil" for a in s)
    frac = len(test) / (len(train) + len(test))
    assert 0.2 <= frac <= 0.45  # ~30% held out
