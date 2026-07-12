"""Trust scoring engine (Week 4): transparent, rule-based, deterministic."""

from __future__ import annotations

from trust_api.services.scoring.config import SCORER_VERSION
from trust_api.services.scoring.engine import risk_flags, score
from trust_api.services.scoring.models import ScoringResult

__all__ = ["SCORER_VERSION", "ScoringResult", "risk_flags", "score"]
