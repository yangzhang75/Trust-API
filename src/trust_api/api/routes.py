"""API routes.

The /verify endpoint is added in a later commit; for now this module
exposes an empty router so the app factory can include it.
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()
