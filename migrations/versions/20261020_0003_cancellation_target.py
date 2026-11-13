"""Track the terminal state requested while stopping a Slurm job."""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20261020_0003"
down_revision = "20261020_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "missions",
        sa.Column("cancellation_target", sa.String(length=32), nullable=True),
    )
    op.execute(sa.text(
        "UPDATE missions SET cancellation_target = 'CANCELLED' WHERE status = 'CANCELLING'"
    ))
    op.create_check_constraint(
        "ck_missions_cancellation_target",
        "missions",
        "cancellation_target IS NULL OR cancellation_target IN "
        "('CANCELLED', 'FAILED', 'TIMED_OUT')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_missions_cancellation_target", "missions", type_="check")
    op.drop_column("missions", "cancellation_target")
