"""graph/cluster feature columns on wallet_features

Revision ID: 0004_graph_features
Revises: 0003_wallet_feature_columns
Create Date: 2026-07-05

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_graph_features"
down_revision: str | None = "0003_wallet_feature_columns"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("wallet_features", sa.Column("shared_funder_score", sa.Float(), nullable=True))
    op.add_column(
        "wallet_features", sa.Column("counterparty_overlap_score", sa.Float(), nullable=True)
    )
    op.add_column("wallet_features", sa.Column("funding_chain_depth", sa.Integer(), nullable=True))
    op.add_column(
        "wallet_features", sa.Column("cluster_size_estimate", sa.Integer(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("wallet_features", "cluster_size_estimate")
    op.drop_column("wallet_features", "funding_chain_depth")
    op.drop_column("wallet_features", "counterparty_overlap_score")
    op.drop_column("wallet_features", "shared_funder_score")
