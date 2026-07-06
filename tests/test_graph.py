"""Tests for the graph/cluster feature computation."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from trust_api.db.models import Wallet, WalletFeature, WalletTransaction
from trust_api.services.features.graph import compute_graph_features

A = "0x" + "a" * 40
B = "0x" + "b" * 40
C = "0x" + "c" * 40
Z = "0x" + "d" * 40
F = "0x" + "f" * 40  # shared external funder
X = "0x" + "e" * 40  # shared counterparty


def _wallet(session: Session, address: str) -> int:
    w = Wallet(address=address)
    session.add(w)
    session.flush()
    # a feature row must exist for the graph pass to update
    session.add(WalletFeature(wallet_id=w.id, chain="ethereum", payload={}))
    return w.id


def _tx(session: Session, wid: int, i: int, direction: str, cp: str) -> None:
    session.add(
        WalletTransaction(
            wallet_id=wid,
            chain="ethereum",
            tx_hash=f"0x{wid:032x}{i:032x}",
            block_number=1000 + i,
            block_time=datetime(2025, 1, 1, tzinfo=UTC),
            value_wei=1,
            direction=direction,
            counterparty=cp,
        )
    )


def test_graph_features_on_cluster_and_isolated(db_session: Session) -> None:
    a, b, c, z = (_wallet(db_session, x) for x in (A, B, C, Z))
    # Cluster A->B->C: shared funder F, shared counterparty X, relay funding chain.
    _tx(db_session, a, 1, "in", F)
    _tx(db_session, a, 2, "out", X)
    _tx(db_session, b, 1, "in", A)  # funded by A (relay)
    _tx(db_session, b, 2, "in", F)
    _tx(db_session, b, 3, "out", X)
    _tx(db_session, c, 1, "in", B)  # funded by B (relay)
    _tx(db_session, c, 2, "in", F)
    _tx(db_session, c, 3, "out", X)
    # Isolated wallet with unique counterparties.
    _tx(db_session, z, 1, "in", "0x" + "1" * 40)
    _tx(db_session, z, 2, "out", "0x" + "2" * 40)
    db_session.commit()

    res = compute_graph_features(db_session, [a, b, c, z])

    # cluster component size
    assert res[a]["cluster_size_estimate"] == 3
    assert res[z]["cluster_size_estimate"] == 1
    # shared funder F is used by A, B, C
    assert res[a]["shared_funder_score"] >= 0.33
    assert res[z]["shared_funder_score"] == 0.0
    # counterparty overlap (share X / F) is high in cluster, zero for isolated
    assert res[b]["counterparty_overlap_score"] > 0.3
    assert res[z]["counterparty_overlap_score"] == 0.0
    # relay funding depth: A funded externally (0), B by A (1), C by B (2)
    assert res[a]["funding_chain_depth"] == 0
    assert res[b]["funding_chain_depth"] == 1
    assert res[c]["funding_chain_depth"] == 2

    # persisted to wallet_features
    from sqlalchemy import select

    stored = db_session.execute(
        select(WalletFeature.cluster_size_estimate).where(WalletFeature.wallet_id == a)
    ).scalar_one()
    assert stored == 3


def test_graph_depth_is_cycle_safe(db_session: Session) -> None:
    # A funded by B and B funded by A (mutual) — must not infinite-loop.
    a, b = _wallet(db_session, A), _wallet(db_session, B)
    _tx(db_session, a, 1, "in", B)
    _tx(db_session, b, 1, "in", A)
    db_session.commit()
    res = compute_graph_features(db_session, [a, b])
    assert res[a]["funding_chain_depth"] >= 0  # terminates, no crash


def test_graph_depth_diamond_uses_memo(db_session: Session) -> None:
    # Diamond: D funded by B and C; B and C both funded by A -> memoized revisit.
    a, b, c, d = (_wallet(db_session, x) for x in (A, B, C, Z))
    _tx(db_session, b, 1, "in", A)
    _tx(db_session, c, 1, "in", A)
    _tx(db_session, d, 1, "in", B)
    _tx(db_session, d, 2, "in", C)
    db_session.commit()
    res = compute_graph_features(db_session, [a, b, c, d])
    assert res[d]["funding_chain_depth"] == 2  # D -> B/C -> A


def test_graph_ignores_null_counterparty(db_session: Session) -> None:
    a = _wallet(db_session, A)
    db_session.add(
        WalletTransaction(
            wallet_id=a,
            chain="ethereum",
            tx_hash="0x" + "0" * 64,
            block_number=1,
            block_time=datetime(2025, 1, 1, tzinfo=UTC),
            value_wei=0,
            direction="out",
            counterparty=None,  # null counterparty must be skipped
        )
    )
    db_session.commit()
    res = compute_graph_features(db_session, [a])
    assert res[a]["counterparty_overlap_score"] == 0.0
