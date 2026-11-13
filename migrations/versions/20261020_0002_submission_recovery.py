"""Track submission attempts for safe worker recovery."""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20261020_0002"
down_revision = "20261019_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "missions",
        sa.Column("submission_attempts", sa.Integer(), nullable=False, server_default="0"),
    )
    op.alter_column("missions", "submission_attempts", server_default=None)


def downgrade() -> None:
    op.drop_column("missions", "submission_attempts")
