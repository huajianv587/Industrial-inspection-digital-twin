"""ROS 2/Nav2 adapter boundary with fail-closed observation conversion.

The module keeps ROS imports lazy so the offline test suite does not require a
ROS installation. A ROS deployment must initialize rclpy and provide a node;
this adapter never sends raw velocity commands and never bypasses robot safety
or emergency-stop controls.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import logging
import math
from queue import Empty, Queue
import time
from typing import Any, Callable, Literal, Protocol

from ..models import Observation, Waypoint

logger = logging.getLogger(__name__)

NavigationStatus = Literal["SUCCEEDED", "FAILED", "CANCELLED", "TIMEOUT"]
InspectionState = Literal[
    "PLANNED", "NAVIGATING", "INSPECTING", "COMPLETED", "FAILED", "CANCELLED"
]


class Ros2AdapterError(RuntimeError):
    """A ROS 2 or observation contract operation failed closed."""


@dataclass(frozen=True)
class Nav2Config:
    action_name: str = "/navigate_to_pose"
    map_frame: str = "map"
    navigation_timeout_seconds: float = 120.0
    cancel_timeout_seconds: float = 5.0
    max_retries: int = 1
    retry_delay_seconds: float = 1.0

    def validate(self) -> None:
        if not self.action_name.startswith("/") or ".." in self.action_name:
            raise ValueError("Nav2 action_name must be an absolute ROS name.")
        if not self.map_frame or "/" in self.map_frame:
            raise ValueError("Nav2 map_frame must be a single non-empty frame name.")
        for value, label in (
            (self.navigation_timeout_seconds, "NAV2_NAVIGATION_TIMEOUT_SECONDS"),
            (self.cancel_timeout_seconds, "NAV2_CANCEL_TIMEOUT_SECONDS"),
            (self.retry_delay_seconds, "NAV2_RETRY_DELAY_SECONDS"),
        ):
            if isinstance(value, bool) or not isinstance(value, (int, float)) \
                    or not math.isfinite(value) or value <= 0:
                raise ValueError(f"{label} must be a finite positive number.")
        if type(self.max_retries) is not int or not 0 <= self.max_retries <= 10:
            raise ValueError("NAV2_MAX_RETRIES must be an integer between 0 and 10.")


@dataclass(frozen=True)
class NavigationResult:
    status: NavigationStatus
    attempts: int = 1
    error: str | None = None


class NavigationBackend(Protocol):
    def navigate(
        self,
        waypoint: Waypoint,
        *,
        timeout_seconds: float,
        cancel_timeout_seconds: float,
    ) -> NavigationResult: ...


class ObservationProvider(Protocol):
    def capture(self, waypoint: Waypoint, *, timeout_seconds: float) -> Observation: ...

    def close(self) -> None: ...


class ResilientNav2Navigator:
    """Apply a bounded retry policy around the Nav2 action backend."""

    def __init__(
        self,
        backend: NavigationBackend,
        config: Nav2Config,
        *,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        config.validate()
        self.backend = backend
        self.config = config
        self._sleep = sleep

    def navigate(self, waypoint: Waypoint) -> NavigationResult:
        last = NavigationResult("FAILED", attempts=0, error="Navigation did not start.")
        for attempt in range(1, self.config.max_retries + 2):
            result = self.backend.navigate(
                waypoint,
                timeout_seconds=self.config.navigation_timeout_seconds,
                cancel_timeout_seconds=self.config.cancel_timeout_seconds,
            )
            last = NavigationResult(result.status, attempts=attempt, error=result.error)
            if result.status == "SUCCEEDED":
                return last
            if result.status == "CANCELLED":
                return last
            if attempt <= self.config.max_retries:
                self._sleep(self.config.retry_delay_seconds)
        return last


class Ros2Nav2ActionBackend:
    """Concrete Nav2 NavigateToPose client; requires a running rclpy node."""

    def __init__(self, node: Any, config: Nav2Config) -> None:
        config.validate()
        try:
            import rclpy
            from action_msgs.msg import GoalStatus
            from geometry_msgs.msg import PoseStamped
            from nav2_msgs.action import NavigateToPose
            from rclpy.action import ActionClient
        except ImportError as exc:
            raise Ros2AdapterError(
                "ROS 2 Nav2 dependencies are unavailable; install the target ROS distribution."
            ) from exc
        self._rclpy = rclpy
        self._goal_status = GoalStatus
        self._pose_type = PoseStamped
        self._action_type = NavigateToPose
        self._node = node
        self._config = config
        self._client = ActionClient(node, NavigateToPose, config.action_name)

    def _spin(self, future: Any, timeout_seconds: float) -> Any | None:
        self._rclpy.spin_until_future_complete(
            self._node, future, timeout_sec=timeout_seconds)
        return future.result() if future.done() else None

    def navigate(
        self,
        waypoint: Waypoint,
        *,
        timeout_seconds: float,
        cancel_timeout_seconds: float,
    ) -> NavigationResult:
        try:
            if not self._client.wait_for_server(timeout_sec=timeout_seconds):
                return NavigationResult("TIMEOUT", error="Nav2 action server did not become ready.")
            goal = self._action_type.Goal()
            pose = self._pose_type()
            pose.header.frame_id = self._config.map_frame
            pose.header.stamp = self._node.get_clock().now().to_msg()
            pose.pose.position.x = waypoint.x
            pose.pose.position.y = waypoint.y
            pose.pose.position.z = waypoint.z
            yaw = math.radians(waypoint.yaw_deg)
            pose.pose.orientation.z = math.sin(yaw / 2.0)
            pose.pose.orientation.w = math.cos(yaw / 2.0)
            goal.pose = pose
            goal_future = self._client.send_goal_async(goal)
            goal_handle = self._spin(goal_future, timeout_seconds)
            if goal_handle is None:
                return NavigationResult("TIMEOUT", error="Nav2 goal submission timed out.")
            if not goal_handle.accepted:
                return NavigationResult("FAILED", error="Nav2 rejected the navigation goal.")
            result_future = goal_handle.get_result_async()
            result = self._spin(result_future, timeout_seconds)
            if result is None:
                cancel_future = goal_handle.cancel_goal_async()
                self._spin(cancel_future, cancel_timeout_seconds)
                return NavigationResult("TIMEOUT", error="Nav2 navigation timed out; cancel requested.")
            status = result.status
            if status == self._goal_status.STATUS_SUCCEEDED:
                return NavigationResult("SUCCEEDED")
            if status == self._goal_status.STATUS_CANCELED:
                return NavigationResult("CANCELLED", error="Nav2 navigation was cancelled.")
            return NavigationResult("FAILED", error=f"Nav2 goal ended with status {status}.")
        except Exception as exc:
            logger.exception("Nav2 navigation call failed")
            return NavigationResult("FAILED", error=f"{type(exc).__name__}: {exc}"[:512])


class Ros2TopicObservationProvider:
    """Convert inspection_interfaces observations into the platform contract."""

    def __init__(
        self,
        node: Any,
        *,
        topic_name: str,
        robot_id: str,
        source: str = "robot",
        queue_size: int = 16,
    ) -> None:
        try:
            from inspection_interfaces.msg import InspectionObservation
        except ImportError as exc:
            raise Ros2AdapterError(
                "inspection_interfaces is unavailable; build the ROS 2 workspace first."
            ) from exc
        if not topic_name.startswith("/") or ".." in topic_name:
            raise ValueError("ROS observation topic must be an absolute topic name.")
        if not robot_id.strip():
            raise ValueError("robot_id must be non-empty.")
        self._node = node
        self._robot_id = robot_id
        self._source = source
        self._messages: Queue[Any] = Queue(maxsize=queue_size)
        self._subscription = node.create_subscription(
            InspectionObservation, topic_name, self._on_message, queue_size)

    def _on_message(self, message: Any) -> None:
        try:
            self._messages.put_nowait(message)
        except Exception:
            try:
                self._messages.get_nowait()
                self._messages.put_nowait(message)
            except Empty:
                logger.warning("ROS observation queue is full; dropping newest message")

    @staticmethod
    def _timestamp(message: Any) -> str:
        stamp = getattr(message, "stamp", None)
        if stamp is None:
            raise Ros2AdapterError("ROS observation is missing stamp.")
        seconds = int(stamp.sec) + int(stamp.nanosec) / 1_000_000_000
        return datetime.fromtimestamp(seconds, timezone.utc).isoformat(timespec="milliseconds")

    @staticmethod
    def _json_list(value: Any, label: str) -> list[str]:
        try:
            decoded = json.loads(value)
        except (TypeError, json.JSONDecodeError) as exc:
            raise Ros2AdapterError(f"ROS observation {label} is invalid JSON.") from exc
        if (not isinstance(decoded, list)
                or not decoded
                or any(not isinstance(item, str) or not item.strip() for item in decoded)
                or len(set(decoded)) != len(decoded)):
            raise Ros2AdapterError(f"ROS observation {label} must be unique non-empty strings.")
        return decoded

    def _convert(self, message: Any, waypoint: Waypoint) -> Observation:
        if getattr(message, "source", None) != self._source:
            raise Ros2AdapterError("ROS observation source does not match the adapter.")
        if getattr(message, "robot_id", None) != self._robot_id:
            raise Ros2AdapterError("ROS observation robot_id does not match the adapter.")
        if getattr(message, "waypoint_id", None) != waypoint.waypoint_id:
            raise Ros2AdapterError("ROS observation waypoint_id does not match the waypoint.")
        if getattr(message, "device_id", None) != waypoint.device_id:
            raise Ros2AdapterError("ROS observation device_id does not match the waypoint.")
        sensor_ids = self._json_list(getattr(message, "sensor_ids_json", ""), "sensor_ids_json")
        frame_id = getattr(message, "frame_id", "")
        if not isinstance(frame_id, str) or not frame_id.strip():
            raise Ros2AdapterError("ROS observation frame_id is required.")
        domain: dict[str, Any] = {
            "sensor_provenance": {"sensor_ids": sensor_ids, "frame_id": frame_id},
        }
        domain_json = getattr(message, "domain_json", "")
        if domain_json:
            try:
                extra_domain = json.loads(domain_json)
            except (TypeError, json.JSONDecodeError) as exc:
                raise Ros2AdapterError("ROS observation domain_json is invalid JSON.") from exc
            if not isinstance(extra_domain, dict):
                raise Ros2AdapterError("ROS observation domain_json must be an object.")
            domain.update(extra_domain)
        flags = self._json_list(getattr(message, "quality_flags_json", "[]"), "quality_flags_json") \
            if getattr(message, "quality_flags_json", "") else []
        return Observation(
            sample_id=getattr(message, "sample_id", ""),
            timestamp_utc=self._timestamp(message),
            source=self._source,
            robot_id=self._robot_id,
            waypoint_id=waypoint.waypoint_id,
            device_id=waypoint.device_id,
            pressure_mpa=float(message.pressure_mpa) if message.has_pressure else None,
            temperature_c=float(message.temperature_c) if message.has_temperature else None,
            ambient_temperature_c=(
                float(message.ambient_temperature_c) if message.has_ambient_temperature else None),
            cabinet_door_closed=(
                bool(message.cabinet_door_closed) if message.has_door_state else None),
            leak_detected=bool(message.leak_detected) if message.has_leak_state else None,
            sensor_confidence={},
            model_version=message.model_version or None,
            calibration_version=message.calibration_version or None,
            quality_flags=flags,
            inference_latency_ms=(
                float(message.inference_latency_ms) if message.has_inference_latency else None),
            domain=domain,
        )

    def capture(self, waypoint: Waypoint, *, timeout_seconds: float) -> Observation:
        deadline = time.monotonic() + timeout_seconds
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise Ros2AdapterError("Timed out waiting for a matching ROS observation.")
            try:
                message = self._messages.get(timeout=remaining)
            except Empty as exc:
                raise Ros2AdapterError("Timed out waiting for a matching ROS observation.") from exc
            observation = self._convert(message, waypoint)
            if not observation.sample_id.strip():
                raise Ros2AdapterError("ROS observation sample_id is required.")
            return observation

    def close(self) -> None:
        destroy = getattr(self._node, "destroy_subscription", None)
        if callable(destroy):
            destroy(self._subscription)


class Ros2RobotAdapter:
    """RobotAdapter implementation using Nav2 for navigation and a topic provider."""

    source: Literal["robot"] = "robot"

    def __init__(
        self,
        navigator: ResilientNav2Navigator,
        observations: ObservationProvider,
        *,
        capture_timeout_seconds: float = 30.0,
    ) -> None:
        if capture_timeout_seconds <= 0 or not math.isfinite(capture_timeout_seconds):
            raise ValueError("capture_timeout_seconds must be finite and positive.")
        self.navigator = navigator
        self.observations = observations
        self.capture_timeout_seconds = capture_timeout_seconds
        self.state: InspectionState = "PLANNED"
        self.last_navigation: NavigationResult | None = None
        self._navigated_waypoint_id: str | None = None

    def navigate(self, waypoint: Waypoint) -> bool:
        self.state = "NAVIGATING"
        self._navigated_waypoint_id = None
        result = self.navigator.navigate(waypoint)
        self.last_navigation = result
        if result.status != "SUCCEEDED":
            self.state = "CANCELLED" if result.status == "CANCELLED" else "FAILED"
            logger.warning("ROS navigation did not complete", extra={
                "waypoint_id": waypoint.waypoint_id,
                "navigation_status": result.status,
                "attempts": result.attempts,
            })
            return False
        self._navigated_waypoint_id = waypoint.waypoint_id
        return True

    def capture(self, waypoint: Waypoint, index: int) -> Observation:
        if (self.last_navigation is None
                or self.last_navigation.status != "SUCCEEDED"
                or self._navigated_waypoint_id != waypoint.waypoint_id):
            self.state = "FAILED"
            raise Ros2AdapterError(
                "Cannot capture before successful Nav2 navigation for this waypoint.")
        self.state = "INSPECTING"
        try:
            observation = self.observations.capture(
                waypoint, timeout_seconds=self.capture_timeout_seconds)
            if observation.source != self.source:
                raise Ros2AdapterError("Observation source does not match the ROS robot adapter.")
            if observation.waypoint_id != waypoint.waypoint_id \
                    or observation.device_id != waypoint.device_id:
                raise Ros2AdapterError("Observation identity does not match the waypoint.")
            self.state = "COMPLETED"
            return observation
        except Exception:
            self.state = "FAILED"
            raise

    def close(self) -> None:
        self.observations.close()
