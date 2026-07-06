"""Graph / cluster features (Week 4 reinforcement, "B").

These are computed over a SET of in-sample wallets (transductive): they
describe how a wallet relates to the others in the labeled set via the
funding + counterparty graph. Computed in a batch pass and stored on
wallet_features. In production, "in-sample" would be a wallet's ingested
neighborhood; here it is the labeled/evaluated set.

Features:
  * shared_funder_score        — fraction of my top-3 funders also used by
                                 another in-sample wallet (0..1)
  * counterparty_overlap_score — max Jaccard overlap of my counterparty set
                                 with any other in-sample wallet (0..1)
  * funding_chain_depth        — longest chain of in-sample funders ending
                                 at me (relay depth; 0 = funded externally)
  * cluster_size_estimate      — size of my connected component in the
                                 shared-funder / shared-counterparty /
                                 direct-transfer graph over in-sample wallets
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from trust_api.db.models import Wallet, WalletTransaction

TOP_FUNDERS = 3


@dataclass
class _WalletGraphData:
    address: str
    counterparties: set[str]
    top_funders: set[str]


def _load(session: Session, wallet_ids: list[int]) -> dict[int, _WalletGraphData]:
    addr_by_id = dict(
        session.execute(select(Wallet.id, Wallet.address).where(Wallet.id.in_(wallet_ids))).all()
    )
    cps: dict[int, set[str]] = {wid: set() for wid in wallet_ids}
    funder_counts: dict[int, Counter] = {wid: Counter() for wid in wallet_ids}
    rows = session.execute(
        select(
            WalletTransaction.wallet_id, WalletTransaction.direction, WalletTransaction.counterparty
        ).where(WalletTransaction.wallet_id.in_(wallet_ids))
    ).all()
    for wid, direction, cp in rows:
        if not cp:
            continue
        cp = cp.lower()
        cps[wid].add(cp)
        if direction == "in":
            funder_counts[wid][cp] += 1
    return {
        wid: _WalletGraphData(
            address=addr_by_id[wid].lower(),
            counterparties=cps[wid],
            top_funders={a for a, _ in funder_counts[wid].most_common(TOP_FUNDERS)},
        )
        for wid in wallet_ids
    }


def compute_graph_features(session: Session, wallet_ids: list[int]) -> dict[int, dict]:
    """Compute the 4 graph features for ``wallet_ids`` and persist them."""
    data = _load(session, wallet_ids)
    addr_to_id = {d.address: wid for wid, d in data.items()}

    # How many in-sample wallets use each funder.
    funder_users: Counter = Counter()
    for d in data.values():
        for f in d.top_funders:
            funder_users[f] += 1

    # Directed in-sample funder edges: funder_wallet -> wallet.
    parents: dict[int, list[int]] = {wid: [] for wid in wallet_ids}
    for wid, d in data.items():
        for f in d.top_funders:
            if f in addr_to_id and addr_to_id[f] != wid:
                parents[wid].append(addr_to_id[f])

    # Undirected cluster edges: shared funder OR shared counterparty OR direct transfer.
    adj: dict[int, set[int]] = {wid: set() for wid in wallet_ids}
    ids = list(wallet_ids)
    for i, a in enumerate(ids):
        da = data[a]
        for b in ids[i + 1 :]:
            db = data[b]
            linked = (
                (da.top_funders & db.top_funders)
                or (da.counterparties & db.counterparties)
                or (db.address in da.counterparties)
                or (da.address in db.counterparties)
            )
            if linked:
                adj[a].add(b)
                adj[b].add(a)

    results: dict[int, dict] = {}
    for wid, d in data.items():
        shared = sum(1 for f in d.top_funders if funder_users[f] >= 2)
        overlap = 0.0
        for other, od in data.items():
            if other == wid or not (d.counterparties or od.counterparties):
                continue
            # At least one set is non-empty here, so the union is non-empty.
            union = d.counterparties | od.counterparties
            overlap = max(overlap, len(d.counterparties & od.counterparties) / len(union))
        results[wid] = {
            "shared_funder_score": round(shared / TOP_FUNDERS, 6),
            "counterparty_overlap_score": round(overlap, 6),
            "funding_chain_depth": _depth(wid, parents),
            "cluster_size_estimate": _component_size(wid, adj),
        }

    _persist(session, results)
    return results


def _depth(wid: int, parents: dict[int, list[int]]) -> int:
    """Longest chain of in-sample funders ending at ``wid`` (cycle-safe)."""
    memo: dict[int, int] = {}

    def visit(node: int, stack: frozenset[int]) -> int:
        if node in memo:
            return memo[node]
        if node in stack:
            return 0  # cycle guard
        best = 0
        for p in parents.get(node, ()):
            best = max(best, 1 + visit(p, stack | {node}))
        memo[node] = best
        return best

    return visit(wid, frozenset())


def _component_size(wid: int, adj: dict[int, set[int]]) -> int:
    seen = {wid}
    stack = [wid]
    while stack:
        cur = stack.pop()
        for nxt in adj[cur]:
            if nxt not in seen:
                seen.add(nxt)
                stack.append(nxt)
    return len(seen)


def _persist(session: Session, results: dict[int, dict]) -> None:
    from trust_api.db.models import WalletFeature

    for wid, vals in results.items():
        session.query(WalletFeature).filter(WalletFeature.wallet_id == wid).update(vals)
    session.commit()
