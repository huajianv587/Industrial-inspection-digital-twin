"""Add durable, idempotent EAM submission state."""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20261026_0007"
down_revision = "20261021_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "eam_submissions",
        sa.Column("ticket_id", sa.String(length=128),
                  sa.ForeignKey("work_orders.ticket_id"), primary_key=True),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False, unique=True),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("external_id", sa.String(length=256)),
        sa.Column("response_json", sa.Text()),
        sa.Column("last_error", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "status IN ('PENDING', 'SUBMITTED', 'FAILED')",
            name="ck_eam_submissions_status",
        ),
    )
    op.create_index(
        "ix_eam_submissions_status_updated",
        "eam_submissions",
        ["status", "updated_at"],
    )
    op.execute("GRANT SELECT, INSERT, UPDATE ON TABLE public.eam_submissions TO inspection_app")
    op.execute("ALTER TABLE public.eam_submissions ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY inspection_app_access ON public.eam_submissions "
        "FOR ALL TO inspection_app USING (true) WITH CHECK (true)")


def downgrade() -> None:
    op.drop_index("ix_eam_submissions_status_updated", table_name="eam_submissions")
    op.drop_table("eam_submissions")
