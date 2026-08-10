"""Shared test helpers for the mock platform: a fake TrustClient."""

from __future__ import annotations

from trust_api.demo.platform.client import TrustError


class FakeTrustClient:
    """Stand-in for TrustClient. Maps wallet -> canned assessment, or raises a
    configured TrustError. Lets endpoint tests run with no live Trust API."""

    def __init__(
        self,
        assessments: dict[str, dict] | None = None,
        *,
        errors: dict[str, TrustError] | None = None,
        batch_assessments: dict[str, dict] | None = None,
    ) -> None:
        self._assessments = assessments or {}
        # Optional distinct results for verify_batch — models the real world
        # where the graph-aware batch sees signals single-wallet /verify can't.
        self._batch_assessments = batch_assessments or {}
        self._errors = errors or {}
        self.verify_calls: list[str] = []
        self.proof_calls: list[str] = []
        self.batch_calls: list[list[str]] = []

    def verify(self, wallet: str, chains: list[str] | None = None) -> dict:
        self.verify_calls.append(wallet)
        if wallet in self._errors:
            raise self._errors[wallet]
        return self._assessments.get(wallet, {"trust_tier": "unknown", "risk_flags": []})

    def generate_proof(self, wallet: str, chains: list[str] | None = None) -> dict:
        self.proof_calls.append(wallet)
        if wallet in self._errors:
            raise self._errors[wallet]
        return {"encoded": f"proof-for-{wallet}", "summary": f"summary {wallet}"}

    def verify_batch(self, wallets: list[str], chains: list[str] | None = None) -> list[dict]:
        self.batch_calls.append(list(wallets))
        # Prefer the batch-specific assessment (graph-aware), else the single one.
        return [
            {
                "wallet": w,
                **(
                    self._batch_assessments.get(w)
                    or self._assessments.get(w)
                    or {"trust_tier": "unknown", "risk_flags": []}
                ),
            }
            for w in wallets
        ]


def assessment(tier: str, *, likelihood: str = "medium", flags: list[str] | None = None) -> dict:
    return {"trust_tier": tier, "human_likelihood": likelihood, "risk_flags": flags or []}
