"""wallet_transactions table + wallet ingestion aggregates

Revision ID: 0002_wallet_transactions
Revises: 0001_initial
Create Date: 2026-06-30

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002_wallet_transactions"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Ingestion aggregates on the existing wallets table.
    op.add_column("wallets", sa.Column("first_seen", sa.DateTime(timezone=True), nullable=True))
    op.add_column("wallets", sa.Column("last_seen", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "wallets",
        sa.Column("tx_count", sa.Integer(), server_default="0", nullable=False),
    )

    op.create_table(
        "wallet_transactions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("wallet_id", sa.Integer(), nullable=False),
        sa.Column("chain", sa.String(length=32), nullable=False),
        sa.Column("tx_hash", sa.String(length=66), nullable=False),
        sa.Column("block_number", sa.BigInteger(), nullable=False),
        sa.Column("block_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("value_wei", sa.Numeric(precision=80, scale=0), nullable=False),
        sa.Column("direction", sa.String(length=8), nullable=False),
        sa.Column("counterparty", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["wallet_id"], ["wallets.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("wallet_id", "tx_hash", name="uq_wallet_tx_hash"),
    )
    op.create_index("ix_wallet_transactions_wallet_id", "wallet_transactions", ["wallet_id"])


def downgrade() -> None:
    op.drop_index("ix_wallet_transactions_wallet_id", table_name="wallet_transactions")
    op.drop_table("wallet_transactions")
    op.drop_column("wallets", "tx_count")
    op.drop_column("wallets", "last_seen")
    op.drop_column("wallets", "first_seen")
