"""API-key gate for the internal dashboard.

Reuses the same key mechanism as the rest of the service: a dashboard-admin
key (``DASHBOARD_API_KEYS``) OR any regular ``API_KEYS`` entry grants access.
The dashboard is closed (rejects everything) when no keys are configured, so
it is never publicly accessible by default.
"""

from __future__ import annotations

import hmac

from trust_api.config import Settings


def allowed_dashboard_keys(settings: Settings) -> set[str]:
    """Keys that may access the dashboard: admin keys ∪ regular API keys."""
    return settings.dashboard_key_set | settings.api_key_set


def verify_dashboard_key(settings: Settings, api_key: str | None) -> bool:
    """Constant-time check that ``api_key`` is an accepted dashboard key.

    Returns False for a missing key or when no keys are configured (closed).
    """
    allowed = allowed_dashboard_keys(settings)
    if not api_key or not allowed:
        return False
    matched = False
    for known in allowed:  # no early return — work is independent of which key matched
        if hmac.compare_digest(api_key, known):
            matched = True
    return matched
