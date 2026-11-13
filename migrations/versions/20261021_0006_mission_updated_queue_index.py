"""Index mission state transitions and retry queue scans."""
from __future__ import annotations

from alembic import op


revision = "20261021_0006"
down_revision = "20261020_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_missions_status_updated", "missions", ["status", "updated_at"])


def downgrade() -> None:
    op.drop_index("ix_missions_status_updated", table_name="missions")
