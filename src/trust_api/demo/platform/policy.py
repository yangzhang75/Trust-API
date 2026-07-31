"""Acceptance policies for the mock platform's scenarios (pure functions).

Each ``decide_*`` takes a Trust API ``/verify`` assessment dict and returns a
small decision object. Kept pure and side-effect-free so the policy logic is
trivially unit-testable, independent of HTTP.
"""

from __future__ import annotations

from dataclasses import dataclass

SYBIL_FLAG = "sybil_suspected"


def _tier(assessment: dict) -> str:
    return assessment.get("trust_tier", "unknown")


def _flags(assessment: dict) -> list[str]:
    return assessment.get("risk_flags") or []


@dataclass(frozen=True)
class LoginDecision:
    accepted: bool
    tier: str
    reason: str


def decide_login(assessment: dict) -> LoginDecision:
    """Scenario A — social login.

    Precedence: an explicit ``sybil_suspected`` flag rejects regardless of
    tier; otherwise silver+ is accepted, bronze is accepted-but-flagged, and an
    unexpected/missing tier is rejected.
    """
    tier = _tier(assessment)
    if SYBIL_FLAG in _flags(assessment):
        return LoginDecision(accepted=False, tier=tier, reason="sybil_suspected")
    if tier in ("silver", "gold"):
        return LoginDecision(accepted=True, tier=tier, reason="tier_ok")
    if tier == "bronze":
        return LoginDecision(accepted=True, tier=tier, reason="flagged_low_tier")
    return LoginDecision(accepted=False, tier=tier, reason="unknown_tier")
