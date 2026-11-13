"""Track worker liveness for operations dashboards."""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20261020_0005"
down_revision = "20261020_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "service_heartbeats",
        sa.Column("service_name", sa.String(length=64), primary_key=True),
        sa.Column("instance_id", sa.String(length=64), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("execution_backend", sa.String(length=16), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_error_type", sa.String(length=128)),
        sa.CheckConstraint(
            "state IN ('starting', 'working', 'idle', 'degraded', 'stopped')",
            name="ck_service_heartbeats_state",
        ),
        sa.CheckConstraint(
            "execution_backend IN ('offline', 'slurm')",
            name="ck_service_heartbeats_backend",
        ),
    )
    op.execute("GRANT SELECT, INSERT, UPDATE ON TABLE public.service_heartbeats TO inspection_app")
    op.execute("ALTER TABLE public.service_heartbeats ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY inspection_app_access ON public.service_heartbeats "
        "FOR ALL TO inspection_app USING (true) WITH CHECK (true)")


def downgrade() -> None:
    op.drop_table("service_heartbeats")
