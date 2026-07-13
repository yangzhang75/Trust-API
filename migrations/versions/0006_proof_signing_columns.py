"""proof signing columns: key_id + revoked

Revision ID: 0006_proof_signing_columns
Revises: 0005_trust_score_history
Create Date: 2026-07-13

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_proof_signing_columns"
down_revision: str | None = "0005_trust_score_history"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("proofs", sa.Column("key_id", sa.String(length=32), nullable=True))
    op.add_column(
        "proofs", sa.Column("revoked", sa.Boolean(), server_default="false", nullable=False)
    )


def downgrade() -> None:
    op.drop_column("proofs", "revoked")
    op.drop_column("proofs", "key_id")
