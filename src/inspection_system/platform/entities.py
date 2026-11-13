from __future__ import annotations

from datetime import datetime, timezone
from sqlalchemy import (
    CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column
from .db import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class MissionRecord(Base):
    __tablename__ = "missions"
    __table_args__ = (
        Index("ix_missions_status_created", "status", "created_at"),
        Index("ix_missions_status_updated", "status", "updated_at"),
        CheckConstraint(
            "cancellation_target IS NULL OR cancellation_target IN "
            "('CANCELLED', 'FAILED', 'TIMED_OUT')",
            name="ck_missions_cancellation_target",
        ),
    )

    run_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    site_id: Mapped[str] = mapped_column(String(128), nullable=False)
    robot_id: Mapped[str] = mapped_column(String(128), nullable=False)
    execution_backend: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    seed: Mapped[int] = mapped_column(Integer, nullable=False)
    manifest_json: Mapped[str] = mapped_column(Text, nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(String(128), unique=True)
    submission_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cancellation_target: Mapped[str | None] = mapped_column(String(32))
    slurm_job_id: Mapped[str | None] = mapped_column(String(128))
    remote_dir: Mapped[str | None] = mapped_column(Text)
    poll_failures: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    result_json: Mapped[str | None] = mapped_column(Text)
    result_hash: Mapped[str | None] = mapped_column(String(64))
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now,
                                                  onupdate=utc_now)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class WorkOrderRecord(Base):
    __tablename__ = "work_orders"
    __table_args__ = (Index("ix_work_orders_status_created", "review_status", "created_at"),)

    ticket_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("missions.run_id"), nullable=False)
    severity: Mapped[str] = mapped_column(String(32), nullable=False)
    review_status: Mapped[str] = mapped_column(String(32), nullable=False, default="PENDING")
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    reviewed_by: Mapped[str | None] = mapped_column(String(256))
    review_decision: Mapped[str | None] = mapped_column(String(32))
    review_comment: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class EamSubmissionRecord(Base):
    __tablename__ = "eam_submissions"
    __table_args__ = (
        Index("ix_eam_submissions_status_updated", "status", "updated_at"),
        CheckConstraint(
            "status IN ('PENDING', 'SUBMITTED', 'FAILED')",
            name="ck_eam_submissions_status",
        ),
    )

    ticket_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("work_orders.ticket_id"), primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    external_id: Mapped[str | None] = mapped_column(String(256))
    response_json: Mapped[str | None] = mapped_column(Text)
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now,
                                                  onupdate=utc_now)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ArtifactRecord(Base):
    __tablename__ = "artifacts"
    __table_args__ = (UniqueConstraint("run_id", "name", name="uq_artifact_run_name"),)

    artifact_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("missions.run_id"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    storage_path: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class AuditEventRecord(Base):
    __tablename__ = "audit_events"
    __table_args__ = (Index("ix_audit_events_resource", "resource_type", "resource_id"),)

    event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    actor: Mapped[str] = mapped_column(String(256), nullable=False)
    actor_role: Mapped[str] = mapped_column(String(32), nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_id: Mapped[str] = mapped_column(String(128), nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ServiceHeartbeatRecord(Base):
    __tablename__ = "service_heartbeats"
    __table_args__ = (
        CheckConstraint(
            "state IN ('starting', 'working', 'idle', 'degraded', 'stopped')",
            name="ck_service_heartbeats_state",
        ),
        CheckConstraint(
            "execution_backend IN ('offline', 'slurm')",
            name="ck_service_heartbeats_backend",
        ),
    )

    service_name: Mapped[str] = mapped_column(String(64), primary_key=True)
    instance_id: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    execution_backend: Mapped[str] = mapped_column(String(16), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_error_type: Mapped[str | None] = mapped_column(String(128))
