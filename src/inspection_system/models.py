from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Severity(str, Enum):
    NORMAL = "NORMAL"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"
    UNKNOWN = "UNKNOWN"


class MissionStatus(str, Enum):
    PLANNED = "PLANNED"
    NAVIGATING = "NAVIGATING"
    INSPECTING = "INSPECTING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


@dataclass(frozen=True)
class Waypoint:
    waypoint_id: str
    device_id: str
    device_name: str
    zone: str
    x: float
    y: float
    z: float
    yaw_deg: float
    pressure_max_mpa: float | None
    warning_temp_c: float
    critical_temp_c: float
    require_door_closed: bool = False
    asset_id: str | None = None


@dataclass
class Observation:
    sample_id: str
    timestamp_utc: str
    source: str
    robot_id: str
    waypoint_id: str
    device_id: str
    pressure_mpa: float | None = None
    temperature_c: float | None = None
    ambient_temperature_c: float | None = None
    cabinet_door_closed: bool | None = None
    leak_detected: bool | None = None
    sensor_confidence: dict[str, float] = field(default_factory=dict)
    model_version: str | None = None
    calibration_version: str | None = None
    quality_flags: list[str] = field(default_factory=list)
    inference_latency_ms: float | None = None
    domain: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Anomaly:
    code: str
    severity: Severity
    message: str
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass
class Assessment:
    severity: Severity
    anomalies: list[Anomaly]
    data_quality: str
    source: str


@dataclass
class WorkOrder:
    ticket_id: str
    created_at_utc: str
    site_id: str
    zone: str
    robot_id: str
    waypoint_id: str
    device_id: str
    device_name: str
    severity: Severity
    source: str
    observations: dict[str, Any]
    anomaly_codes: list[str]
    anomaly_messages: list[str]
    recommended_actions: list[str]
    requires_human_review: bool = True


@dataclass
class WaypointResult:
    waypoint_id: str
    device_id: str
    navigation_status: str
    inspection_status: str
    observation: Observation | None
    assessment: Assessment | None
    work_order: WorkOrder | None
    error: str | None = None


@dataclass
class InspectionRun:
    run_id: str
    site_id: str
    robot_id: str
    started_at_utc: str
    finished_at_utc: str
    status: str
    results: list[WaypointResult]
    source: str = "synthetic_simulation"
