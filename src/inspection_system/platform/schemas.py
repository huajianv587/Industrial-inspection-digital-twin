from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MissionCreate(StrictModel):
    site_id: str = Field(min_length=1, max_length=128)
    waypoint_ids: list[str] = Field(min_length=1, max_length=100)
    seed: int = Field(default=42, ge=0, le=2**31 - 1)
    execution_backend: Literal["offline", "slurm"] | None = None
    render_backend: Literal["none", "svg", "blender", "auto"] = "none"
    render_quality: Literal["preview", "production", "ultra"] = "production"
    render_resolution: int = Field(default=1280, ge=640, le=4096)


class MissionView(BaseModel):
    run_id: str
    site_id: str
    robot_id: str
    execution_backend: str
    status: str
    seed: int
    slurm_job_id: str | None
    error: str | None
    created_at: datetime
    updated_at: datetime
    finished_at: datetime | None


class ArtifactView(BaseModel):
    artifact_id: str
    run_id: str
    name: str
    sha256: str
    size_bytes: int
    source: str
    created_at: datetime


class WorkOrderReview(StrictModel):
    decision: Literal["ACKNOWLEDGED", "DISMISSED"]
    comment: str = Field(min_length=3, max_length=2000)


class ResultManifest(StrictModel):
    schema_version: Literal[1]
    run_id: str
    source: str = Field(min_length=1, max_length=64)
    software_version: str = Field(min_length=1, max_length=64)
    config_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    artifacts: list["ArtifactDescriptor"] = Field(default_factory=list)


class ArtifactDescriptor(StrictModel):
    name: str = Field(min_length=1, max_length=255, pattern=r"^[A-Za-z0-9._-]+$")
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(ge=0)


class ResultImport(StrictModel):
    manifest: ResultManifest
    inspection_run: dict[str, Any]
