"""usage_event columns: method + api_key_hash + response_duration_ms

Revision ID: 0007_usage_event_columns
Revises: 0006_proof_signing_columns
Create Date: 2026-07-16

Week 8: the API now logs one usage_events row per request. These columns
capture method, the hashed (privacy-preserving) API key, and the response
duration. The api_keys table / auth mechanism is intentionally NOT migrated
this round — api_key_id stays unused and api_keys stays empty.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_usage_event_columns"
down_revision: str | None = "0006_proof_signing_columns"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("usage_events", sa.Column("method", sa.String(length=8), nullable=True))
    op.add_column("usage_events", sa.Column("api_key_hash", sa.String(length=64), nullable=True))
    op.add_column("usage_events", sa.Column("response_duration_ms", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("usage_events", "response_duration_ms")
    op.drop_column("usage_events", "api_key_hash")
    op.drop_column("usage_events", "method")
