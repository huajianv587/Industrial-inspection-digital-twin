"""Create the initial inspection platform schema."""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20261019_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "missions",
        sa.Column("run_id", sa.String(length=64), primary_key=True),
        sa.Column("site_id", sa.String(length=128), nullable=False),
        sa.Column("robot_id", sa.String(length=128), nullable=False),
        sa.Column("execution_backend", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("seed", sa.Integer(), nullable=False),
        sa.Column("manifest_json", sa.Text(), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), unique=True),
        sa.Column("slurm_job_id", sa.String(length=128)),
        sa.Column("remote_dir", sa.Text()),
        sa.Column("poll_failures", sa.Integer(), nullable=False),
        sa.Column("result_json", sa.Text()),
        sa.Column("result_hash", sa.String(length=64)),
        sa.Column("error", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_missions_status_created", "missions", ["status", "created_at"])

    op.create_table(
        "work_orders",
        sa.Column("ticket_id", sa.String(length=128), primary_key=True),
        sa.Column("run_id", sa.String(length=64), sa.ForeignKey("missions.run_id"), nullable=False),
        sa.Column("severity", sa.String(length=32), nullable=False),
        sa.Column("review_status", sa.String(length=32), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("reviewed_by", sa.String(length=256)),
        sa.Column("review_decision", sa.String(length=32)),
        sa.Column("review_comment", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
    )
    op.create_index(
        "ix_work_orders_status_created", "work_orders", ["review_status", "created_at"])

    op.create_table(
        "artifacts",
        sa.Column("artifact_id", sa.String(length=64), primary_key=True),
        sa.Column("run_id", sa.String(length=64), sa.ForeignKey("missions.run_id"), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("storage_path", sa.Text(), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("run_id", "name", name="uq_artifact_run_name"),
    )

    op.create_table(
        "audit_events",
        sa.Column("event_id", sa.String(length=64), primary_key=True),
        sa.Column("actor", sa.String(length=256), nullable=False),
        sa.Column("actor_role", sa.String(length=32), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("resource_type", sa.String(length=64), nullable=False),
        sa.Column("resource_id", sa.String(length=128), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_audit_events_resource", "audit_events", ["resource_type", "resource_id"])

    op.execute("GRANT USAGE ON SCHEMA public TO inspection_app")
    op.execute("GRANT SELECT, INSERT, UPDATE ON TABLE public.missions, public.work_orders "
               "TO inspection_app")
    op.execute("GRANT SELECT, INSERT ON TABLE public.artifacts, public.audit_events "
               "TO inspection_app")
    for table_name in ("missions", "work_orders", "artifacts", "audit_events"):
        op.execute(f"ALTER TABLE public.{table_name} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY inspection_app_access ON public.{table_name} "
            "FOR ALL TO inspection_app USING (true) WITH CHECK (true)")


def downgrade() -> None:
    op.drop_index("ix_audit_events_resource", table_name="audit_events")
    op.drop_table("audit_events")
    op.drop_table("artifacts")
    op.drop_index("ix_work_orders_status_created", table_name="work_orders")
    op.drop_table("work_orders")
    op.drop_index("ix_missions_status_created", table_name="missions")
    op.drop_table("missions")
