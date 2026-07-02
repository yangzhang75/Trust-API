"""behavioral feature columns on wallet_features

Revision ID: 0003_wallet_feature_columns
Revises: 0002_wallet_transactions
Create Date: 2026-07-02

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003_wallet_feature_columns"
down_revision: str | None = "0002_wallet_transactions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_INT_COLS = (
    "wallet_age_days",
    "tx_count",
    "active_days",
    "counterparty_count",
    "burst_score",
    "recency_days",
)
_FLOAT_COLS = (
    "tx_per_active_day",
    "counterparty_diversity_ratio",
    "inbound_ratio",
)


def upgrade() -> None:
    for col in _INT_COLS:
        op.add_column("wallet_features", sa.Column(col, sa.Integer(), nullable=True))
    for col in _FLOAT_COLS:
        op.add_column("wallet_features", sa.Column(col, sa.Float(), nullable=True))
    op.add_column("wallet_features", sa.Column("dormancy_flag", sa.Boolean(), nullable=True))
    op.create_unique_constraint(
        "uq_wallet_features_wallet_chain", "wallet_features", ["wallet_id", "chain"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_wallet_features_wallet_chain", "wallet_features", type_="unique")
    op.drop_column("wallet_features", "dormancy_flag")
    for col in (*_FLOAT_COLS, *_INT_COLS):
        op.drop_column("wallet_features", col)
