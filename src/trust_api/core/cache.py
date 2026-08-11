"""Short-TTL Redis cache for /verify assessments (Week 12 performance).

Caches the SCORE, not the proof — so a cache hit still mints a fresh, uniquely
nonced proof with a fresh expiry. Best-effort: any Redis error degrades to a
miss / no-op, so caching can never break /verify. Keyed by SCORER_VERSION so a
scorer bump auto-invalidates old entries. Whether a request was a hit is
surfaced via the ``X-Cache`` response header, leaving the /verify JSON contract
untouched.
"""

from __future__ import annotations

import json

import redis

from trust_api.schemas.verify import HumanLikelihood, RiskFlag, TrustTier
from trust_api.services.scoring import SCORER_VERSION, ScoringResult


def _key(wallet: str, chains: list[str]) -> str:
    return f"verify:{SCORER_VERSION}:{wallet.lower()}:{','.join(chains)}"


class AssessmentCache:
    """Get/set a ScoringResult in Redis with a short TTL (0 disables)."""

    def __init__(self, client: redis.Redis, ttl_seconds: int) -> None:
        self._redis = client
        self._ttl = ttl_seconds

    @property
    def enabled(self) -> bool:
        return self._ttl > 0

    def get(self, wallet: str, chains: list[str]) -> ScoringResult | None:
        if not self.enabled:
            return None
        try:
            raw = self._redis.get(_key(wallet, chains))
        except redis.RedisError:
            return None
        if raw is None:
            return None
        data = json.loads(raw)
        return ScoringResult(
            human_likelihood=HumanLikelihood(data["human_likelihood"]),
            trust_tier=TrustTier(data["trust_tier"]),
            confidence_score=data["confidence_score"],
            risk_flags=[RiskFlag(f) for f in data["risk_flags"]],
        )

    def set(self, wallet: str, chains: list[str], result: ScoringResult) -> None:
        if not self.enabled:
            return
        payload = json.dumps(
            {
                "human_likelihood": result.human_likelihood.value,
                "trust_tier": result.trust_tier.value,
                "confidence_score": result.confidence_score,
                "risk_flags": [f.value for f in result.risk_flags],
            }
        )
        try:
            self._redis.set(_key(wallet, chains), payload, ex=self._ttl)
        except redis.RedisError:
            pass
