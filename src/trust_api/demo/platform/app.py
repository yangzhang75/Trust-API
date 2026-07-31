"""The mock platform FastAPI app (a client of the Trust API).

Skeleton (settings + Trust API client on app.state + health) plus the scenario
endpoints. All Trust API access goes through ``TrustClient`` over HTTP.
"""

from __future__ import annotations

from fastapi import Depends, FastAPI, HTTPException, Request
from pydantic import BaseModel

from trust_api.demo.platform.client import TrustClient, TrustError
from trust_api.demo.platform.config import MockSettings, get_mock_settings
from trust_api.demo.platform.policy import decide_creator, decide_filter, decide_login


def get_trust_client(request: Request) -> TrustClient:
    """Resolve the Trust API client stashed on app.state (overridable in tests)."""
    return request.app.state.trust_client


def _assess(client: TrustClient, wallet: str) -> dict | None:
    """Call Trust API /verify, translating upstream errors for a real client.

    Returns the assessment, or ``None`` when the Trust API rejects the wallet
    as invalid (HTTP 400) — the caller treats that as a normal rejection. Any
    other upstream failure (auth, rate limit, outage) surfaces as a 502, since
    the mock genuinely cannot make a decision then.
    """
    try:
        return client.verify(wallet)
    except TrustError as exc:
        if exc.status_code == 400:
            return None
        raise HTTPException(status_code=502, detail=f"Trust API unavailable: {exc.detail}") from exc


def _generate_proof_or_502(client: TrustClient, wallet: str) -> dict:
    try:
        return client.generate_proof(wallet)
    except TrustError as exc:
        raise HTTPException(
            status_code=502, detail=f"Trust API proof failed: {exc.detail}"
        ) from exc


class WalletRequest(BaseModel):
    wallet: str


class LoginResponse(BaseModel):
    accepted: bool
    tier: str
    reason: str


class CreatorResponse(BaseModel):
    approved: bool
    tier: str
    reason: str
    proof: dict | None = None


class BatchRequest(BaseModel):
    wallets: list[str]


class FilterEntry(BaseModel):
    wallet: str
    tier: str
    reason: str


class BatchResponse(BaseModel):
    kept: list[FilterEntry]
    removed: list[FilterEntry]


def create_mock_app(settings: MockSettings | None = None) -> FastAPI:
    settings = settings or get_mock_settings()
    app = FastAPI(title="Mock Platform — Trust API client", version="0.1.0")
    app.state.settings = settings
    app.state.trust_client = TrustClient(settings.trust_api_url, settings.trust_api_key)

    @app.get("/mock/health", tags=["mock"])
    def health() -> dict:
        return {"status": "ok", "trust_api_url": settings.trust_api_url}

    @app.post("/mock/login", response_model=LoginResponse, tags=["mock"])
    def login(
        body: WalletRequest, client: TrustClient = Depends(get_trust_client)
    ) -> LoginResponse:
        """Scenario A — social login: accept silver+, flag bronze, reject sybil."""
        assessment = _assess(client, body.wallet)
        if assessment is None:
            return LoginResponse(accepted=False, tier="invalid", reason="invalid_wallet")
        d = decide_login(assessment)
        return LoginResponse(accepted=d.accepted, tier=d.tier, reason=d.reason)

    @app.post("/mock/creator/apply", response_model=CreatorResponse, tags=["mock"])
    def creator_apply(
        body: WalletRequest, client: TrustClient = Depends(get_trust_client)
    ) -> CreatorResponse:
        """Scenario B — creator verification: gold-only, issue a proof on success."""
        assessment = _assess(client, body.wallet)
        if assessment is None:
            return CreatorResponse(approved=False, tier="invalid", reason="invalid_wallet")
        d = decide_creator(assessment)
        if not d.approved:
            return CreatorResponse(approved=False, tier=d.tier, reason=d.reason)
        proof = _generate_proof_or_502(client, body.wallet)
        return CreatorResponse(approved=True, tier=d.tier, reason=d.reason, proof=proof)

    @app.post("/mock/filter/batch", response_model=BatchResponse, tags=["mock"])
    def filter_batch(
        body: BatchRequest, client: TrustClient = Depends(get_trust_client)
    ) -> BatchResponse:
        """Scenario C — bot filtering in bulk. Per-wallet failure isolation: one
        bad/rate-limited wallet is marked removed, it does not fail the batch."""
        kept: list[FilterEntry] = []
        removed: list[FilterEntry] = []
        for wallet in body.wallets:
            try:
                assessment = client.verify(wallet)
            except TrustError as exc:
                reason = "invalid_wallet" if exc.status_code == 400 else "trust_api_error"
                removed.append(FilterEntry(wallet=wallet, tier="error", reason=reason))
                continue
            d = decide_filter(assessment)
            entry = FilterEntry(wallet=wallet, tier=d.tier, reason=d.reason)
            (kept if d.keep else removed).append(entry)
        return BatchResponse(kept=kept, removed=removed)

    return app
