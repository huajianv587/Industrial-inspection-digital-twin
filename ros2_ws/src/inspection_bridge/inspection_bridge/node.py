from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from threading import Lock
import traceback
import uuid

import rclpy
from rclpy.node import Node

from inspection_interfaces.srv import RunInspection

from inspection_system.config import load_site_config, waypoints_from_config
from inspection_system.mission.orchestrator import MissionOrchestrator
from inspection_system.adapters.ros2_nav2 import (
    Nav2Config,
    ResilientNav2Navigator,
    Ros2Nav2ActionBackend,
    Ros2RobotAdapter,
    Ros2TopicObservationProvider,
)


class InspectionBridgeNode(Node):
    """ROS 2 service boundary with an explicit motion safety gate."""

    def __init__(self) -> None:
        super().__init__("inspection_bridge")
        self.declare_parameter("site_config_path", "configs/site.json")
        self.declare_parameter("robot_id", "")
        self.declare_parameter("observation_topic", "/inspection/observations")
        self.declare_parameter("nav2_action_name", "/navigate_to_pose")
        self.declare_parameter("map_frame", "map")
        self.declare_parameter("capture_timeout_seconds", 30.0)
        self.declare_parameter("max_retries", 1)
        self.declare_parameter("retry_delay_seconds", 1.0)
        self.declare_parameter("allow_motion", False)
        self.declare_parameter("output_dir", "outputs/ros2_runs")

        config_path = Path(str(self.get_parameter("site_config_path").value)).expanduser()
        config = load_site_config(config_path)
        robot_id = str(self.get_parameter("robot_id").value or config["robot"]["robot_id"])
        self._site_config = config
        self._waypoints = waypoints_from_config(config)
        self._robot_id = robot_id
        self._allow_motion = bool(self.get_parameter("allow_motion").value)
        self._output_dir = Path(str(self.get_parameter("output_dir").value)).expanduser()
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="inspection-run")
        self._run_state_lock = Lock()
        self._active = False
        self._active_run_id: str | None = None

        nav_config = Nav2Config(
            action_name=str(self.get_parameter("nav2_action_name").value),
            map_frame=str(self.get_parameter("map_frame").value),
            max_retries=int(self.get_parameter("max_retries").value),
            retry_delay_seconds=float(self.get_parameter("retry_delay_seconds").value),
        )
        backend = Ros2Nav2ActionBackend(self, nav_config)
        provider = Ros2TopicObservationProvider(
            self,
            topic_name=str(self.get_parameter("observation_topic").value),
            robot_id=robot_id,
        )
        self._adapter = Ros2RobotAdapter(
            ResilientNav2Navigator(backend, nav_config),
            provider,
            capture_timeout_seconds=float(
                self.get_parameter("capture_timeout_seconds").value),
        )
        self._service = self.create_service(
            RunInspection, "/inspection/run", self._run_request)
        self.get_logger().info(
            f"Inspection bridge ready; allow_motion={self._allow_motion} "
            f"site={config['site_id']} waypoints={len(self._waypoints)}"
        )

    def _run_request(self, request: RunInspection.Request, response: RunInspection.Response):
        if request.site_id != self._site_config["site_id"]:
            response.accepted = False
            response.message = "site_id does not match the loaded site configuration"
            return response
        with self._run_state_lock:
            if self._active:
                response.accepted = False
                response.run_id = self._active_run_id or ""
                response.message = "an inspection run is already active"
                return response
            if not request.dry_run and not self._allow_motion:
                response.accepted = False
                response.message = (
                    "motion is disabled; set allow_motion=true only after safety acceptance"
                )
                return response
            run_id = f"ROS-RUN-{uuid.uuid4().hex[:16].upper()}"
            self._active = True
            self._active_run_id = run_id

        response.accepted = True
        response.run_id = run_id
        response.message = "inspection run accepted"
        try:
            future = self._executor.submit(self._run_mission, run_id, request.dry_run)
        except RuntimeError as exc:
            with self._run_state_lock:
                if self._active_run_id == run_id:
                    self._active = False
                    self._active_run_id = None
            response.accepted = False
            response.message = f"inspection run could not be scheduled: {exc}"
            self.get_logger().error(response.message)
            return response
        future.add_done_callback(lambda completed: self._run_finished(run_id, completed))
        return response

    def _run_mission(self, run_id: str, dry_run: bool) -> None:
        if dry_run:
            self.get_logger().info("Dry-run accepted; no robot motion or observation capture")
            return
        run = MissionOrchestrator(
            self._site_config["site_id"],
            self._robot_id,
            self._waypoints,
            adapter=self._adapter,
            run_id=run_id,
        ).run(self._output_dir / run_id)
        self.get_logger().info(
            f"Inspection run {run_id} finished with status {run.status}"
        )

    def _run_finished(self, run_id: str, future: Future[None]) -> None:
        try:
            future.result()
        except Exception:
            self.get_logger().error(
                f"ROS 2 inspection run {run_id} failed:\n{traceback.format_exc()}"
            )
        finally:
            with self._run_state_lock:
                if self._active_run_id == run_id:
                    self._active = False
                    self._active_run_id = None

    def close(self) -> None:
        self._adapter.close()
        self._executor.shutdown(wait=True, cancel_futures=True)


def main(args=None) -> None:
    rclpy.init(args=args)
    node: InspectionBridgeNode | None = None
    try:
        node = InspectionBridgeNode()
        rclpy.spin(node)
    finally:
        if node is not None:
            node.close()
            node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
