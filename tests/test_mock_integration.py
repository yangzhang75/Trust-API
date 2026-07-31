"""End-to-end integration: mock platform -> REAL Trust API, in-process.

The mock's TrustClient is given a Starlette TestClient bound to the real Trust
API app as its HTTP transport, so each scenario exercises the genuine
/verify + /proof/generate routes over HTTP (ASGI), not a fake. This verifies
the wiring for one wallet per scenario; it does NOT re-test Trust API scoring
or proof correctness (covered by the API's own suite).

With no DB wired into the Trust API here, every wallet scores on neutral
(empty) features -> bronze / low with a ``sybil_suspected`` flag (a brand-new,
inactive wallet), which is the honest deterministic outcome: login rejects,
creator rejects (below gold), filter removes. Gold approvals + real proofs show
up in the live simulator run (see docs/integration-demo.md).
"""

from __future__ import annotations

import base64

from fastapi.testclient import TestClient

from trust_api.config import Settings
from trust_api.db.session import get_db
from trust_api.demo.platform.app import create_mock_app, get_trust_client
from trust_api.demo.platform.client import TrustClient
from trust_api.demo.platform.config import MockSettings
from trust_api.main import create_app

KEY_B64 = base64.b64encode(b"0" * 32).decode()
WALLET = "0x52908400098527886E0F7030069857D2E4169EE7"


def _mock_client_over_real_trust() -> TestClient:
    trust_app = create_app(
        Settings(
            api_keys="itest-key",
            rate_limit_per_minute=1000,
            environment="test",
            proof_signing_key=KEY_B64,
        )
    )
    trust_app.dependency_overrides[get_db] = lambda: None  # no DB -> empty features
    trust_transport = TestClient(trust_app)  # a real httpx.Client bound to the API app
    trust_client = TrustClient("http://trust", "itest-key", client=trust_transport)

    mock_app = create_mock_app(
        MockSettings(trust_api_url="http://trust", trust_api_key="itest-key")
    )
    mock_app.dependency_overrides[get_trust_client] = lambda: trust_client
    return TestClient(mock_app)


def test_end_to_end_one_wallet_per_scenario() -> None:
    mock = _mock_client_over_real_trust()

    # A — social login: empties -> bronze + sybil_suspected -> rejected.
    login = mock.post("/mock/login", json={"wallet": WALLET}).json()
    assert login["accepted"] is False and login["tier"] == "bronze"
    assert login["reason"] == "sybil_suspected"

    # B — creator: bronze is below gold -> rejected, no proof issued.
    creator = mock.post("/mock/creator/apply", json={"wallet": WALLET}).json()
    assert creator["approved"] is False and creator["reason"] == "tier_below_gold"
    assert creator["proof"] is None

    # C — bot filter: sybil_suspected -> removed.
    batch = mock.post("/mock/filter/batch", json={"wallets": [WALLET]}).json()
    removed = {e["wallet"]: e["reason"] for e in batch["removed"]}
    assert removed == {WALLET: "sybil_suspected"}

    # Stats populated for all three scenarios end-to-end.
    stats = mock.get("/mock/stats").json()
    assert set(stats) == {"login", "creator", "filter"}
    assert stats["login"]["total"] == 1
