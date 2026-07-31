"""Traffic simulator (Week 10) — the output IS the demo.

Pumps a mix of real labeled wallets (humans + sybils) through all three mock
scenarios, then reads GET /mock/stats and prints acceptance rates, latencies,
and tier/reason distributions.

``run(http, wallets)`` takes any object with ``.post(path, json=...)`` /
``.get(path)`` returning a response with ``.json()`` — a live ``httpx.Client``
in ``main()`` or a ``TestClient`` in tests — so the whole flow is unit-tested.
``main()`` wires the real HTTP client and is excluded from coverage.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import httpx

DATASET = "data/labeled_wallets.json"


def sample_wallets(n: int = 24, *, path: str = DATASET) -> list[dict]:
    """A human/sybil mix from the labeled dataset — [{address, label}, …]."""
    data = json.loads(Path(path).read_text())["wallets"]
    humans = [w for w in data if w["label"] == "human"]
    sybils = [w for w in data if w["label"] == "sybil"]
    half = n // 2
    picked = humans[:half] + sybils[: n - half]
    return [{"address": w["address"], "label": w["label"]} for w in picked]


def _banner(out: Any, title: str) -> None:
    out("")
    out("=" * 70)
    out(f"  {title}")
    out("=" * 70)


def _print_stats(out: Any, stats: dict, wallets: list[dict]) -> None:
    n_human = sum(1 for w in wallets if w["label"] == "human")
    out(f"\ninput mix: {n_human} human / {len(wallets) - n_human} sybil")
    for scenario, s in stats.items():
        out(
            f"\n[{scenario}] total={s['total']} accepted={s['accepted']} "
            f"rejected={s['rejected']} acceptance_rate={s['acceptance_rate']} "
            f"avg_latency_ms={s['avg_latency_ms']}"
        )
        out(f"    tiers:   {s['tiers']}")
        out(f"    reasons: {s['reasons']}")


def run(http: Any, wallets: list[dict], out: Any = print) -> dict:
    """Drive all three scenarios, then fetch and print /mock/stats."""
    _banner(out, f"Traffic simulator — {len(wallets)} wallets through 3 scenarios")
    addresses = [w["address"] for w in wallets]

    out(f"\n→ Scenario A (social login): {len(wallets)} logins")
    for wallet in addresses:
        http.post("/mock/login", json={"wallet": wallet})

    out(f"→ Scenario B (creator verification): {len(wallets)} applications")
    for wallet in addresses:
        http.post("/mock/creator/apply", json={"wallet": wallet})

    out(f"→ Scenario C (bot filtering): 1 batch of {len(addresses)}")
    http.post("/mock/filter/batch", json={"wallets": addresses})

    stats = http.get("/mock/stats").json()
    _banner(out, "RESULTS (from GET /mock/stats)")
    _print_stats(out, stats, wallets)
    return stats


def main() -> None:  # pragma: no cover
    mock_url = os.environ.get("MOCK_URL", "http://localhost:18001")
    wallets = sample_wallets(int(os.environ.get("SIM_WALLETS", "24")))
    with httpx.Client(base_url=mock_url, timeout=30.0) as http:
        run(http, wallets)


if __name__ == "__main__":  # pragma: no cover
    main()
