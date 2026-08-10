"""Hybrid re-score job (Week 11) — the background half of the Twitter model.

Registration (/mock/login) decides INSTANTLY via single-wallet /verify. This
job periodically re-scores recent accounts together via /verify/batch — where
graph (cluster) features are populated — and RETROACTIVELY suspends any account
that now looks sybil/bronze. That's the whole point: the instant decision can't
see the cluster; the batch can.

Schedule ``rescore_recent`` every ~15 minutes in production (cron / APScheduler).
``POST /mock/rescore`` forces it immediately for demos. Its UX tradeoff (an
active user can be suspended minutes later) is real — see docs/hybrid-integration.md.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

SYBIL_FLAG = "sybil_suspected"
SUSPEND_TIERS = {"bronze"}


def rescore_recent(
    store: Any, client: Any, *, since_minutes: int = 15, now: datetime | None = None
) -> dict:
    """Re-score recently-active accounts as one batch; suspend those that flip.

    Returns ``{"rescored": n, "suspended": [{wallet, reason, tier}, …]}``.
    """
    wallets = store.recent_active_accounts(since_minutes, now=now)
    if not wallets:
        return {"rescored": 0, "suspended": []}

    suspended: list[dict] = []
    for result in client.verify_batch(wallets):
        tier = result.get("trust_tier")
        flags = result.get("risk_flags") or []
        if SYBIL_FLAG in flags:
            reason = "sybil_suspected_on_batch_rescore"
        elif tier in SUSPEND_TIERS:
            reason = "bronze_on_batch_rescore"
        else:
            continue
        store.suspend_account(result["wallet"], reason)
        suspended.append({"wallet": result["wallet"], "reason": reason, "tier": tier})

    return {"rescored": len(wallets), "suspended": suspended}
