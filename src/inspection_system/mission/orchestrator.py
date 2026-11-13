from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import uuid

from ..adapters.contracts import RobotAdapter
from ..adapters.simulation import SimulatedRobotAdapter
from ..models import InspectionRun, Waypoint, WaypointResult
from ..perception.rules import RuleBasedDiagnosticEngine
from ..reporting import write_run_artifacts


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class MissionOrchestrator:
    """System-level inspection workflow with a replaceable robot adapter."""
    def __init__(self, site_id: str, robot_id: str, waypoints: list[Waypoint],
                 adapter: RobotAdapter | None = None,
                 diagnostic_engine: RuleBasedDiagnosticEngine | None = None,
                 run_id: str | None = None):
        self.site_id = site_id
        self.robot_id = robot_id
        self.waypoints = waypoints
        self.adapter = adapter or SimulatedRobotAdapter(robot_id=robot_id)
        if self.adapter.source not in {"synthetic_simulation", "robot"}:
            raise ValueError("Robot adapter source is unsupported.")
        self.engine = diagnostic_engine or RuleBasedDiagnosticEngine()
        self.requested_run_id = run_id

    def run(self, output_dir: str | Path | None = None) -> InspectionRun:
        started = _utc_iso()
        run_id = self.requested_run_id or f"SIM-RUN-{uuid.uuid4().hex[:10].upper()}"
        results: list[WaypointResult] = []
        for index, waypoint in enumerate(self.waypoints, start=1):
            if not self.adapter.navigate(waypoint):
                results.append(WaypointResult(
                    waypoint_id=waypoint.waypoint_id, device_id=waypoint.device_id,
                    navigation_status="FAILED", inspection_status="SKIPPED",
                    observation=None, assessment=None, work_order=None,
                    error="模拟导航适配器报告失败；未采集该航点。"))
                continue
            try:
                observation = self.adapter.capture(waypoint, index)
                if observation.source != self.adapter.source:
                    raise ValueError("Observation source does not match robot adapter source.")
                if (observation.robot_id != self.robot_id
                        or observation.waypoint_id != waypoint.waypoint_id
                        or observation.device_id != waypoint.device_id):
                    raise ValueError("Observation identity does not match the frozen waypoint.")
                observation.sample_id = f"{run_id}-{index:03d}-{waypoint.waypoint_id}"
                assessment = self.engine.assess(observation, waypoint)
                order = self.engine.create_work_order(
                    observation, waypoint, assessment, self.site_id, run_id=run_id)
                results.append(WaypointResult(
                    waypoint_id=waypoint.waypoint_id, device_id=waypoint.device_id,
                    navigation_status="SUCCEEDED", inspection_status="COMPLETED",
                    observation=observation, assessment=assessment, work_order=order))
            except Exception as exc:
                results.append(WaypointResult(
                    waypoint_id=waypoint.waypoint_id, device_id=waypoint.device_id,
                    navigation_status="SUCCEEDED", inspection_status="FAILED",
                    observation=None, assessment=None, work_order=None,
                    error=f"{type(exc).__name__}: {exc}"))
        failed = any(item.inspection_status == "FAILED" or item.navigation_status == "FAILED"
                     for item in results)
        status = "COMPLETED_WITH_ERRORS" if failed else "COMPLETED"
        run = InspectionRun(
            run_id=run_id, site_id=self.site_id, robot_id=self.robot_id,
            started_at_utc=started, finished_at_utc=_utc_iso(),
            status=status, results=results, source=self.adapter.source)
        finalize = getattr(self.adapter, "finalize", None)
        if callable(finalize):
            finalize(run)
        if output_dir is not None:
            write_run_artifacts(run, output_dir)
        return run
