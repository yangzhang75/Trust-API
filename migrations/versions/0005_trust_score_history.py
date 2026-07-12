"""append-only trust_score_history table

Revision ID: 0005_trust_score_history
Revises: 0004_graph_features
Create Date: 2026-07-12

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005_trust_score_history"
down_revision: str | None = "0004_graph_features"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "trust_score_history",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("wallet_id", sa.Integer(), nullable=False),
        sa.Column("human_likelihood", sa.String(length=16), nullable=False),
        sa.Column("trust_tier", sa.String(length=16), nullable=False),
        sa.Column("confidence_score", sa.Numeric(precision=5, scale=4), nullable=False),
        sa.Column("risk_flags", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("scorer_version", sa.String(length=32), nullable=False),
        sa.Column(
            "scored_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["wallet_id"], ["wallets.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("wallet_id", "scorer_version", name="uq_score_history_wallet_version"),
    )
    op.create_index("ix_trust_score_history_wallet_id", "trust_score_history", ["wallet_id"])


def downgrade() -> None:
    op.drop_index("ix_trust_score_history_wallet_id", table_name="trust_score_history")
    op.drop_table("trust_score_history")
