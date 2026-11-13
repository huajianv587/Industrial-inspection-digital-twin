from __future__ import annotations

from dataclasses import dataclass
import json
import unittest

from inspection_system.config import load_site_config, waypoints_from_config
from inspection_system.models import Observation
from inspection_system.adapters.ros2_nav2 import (
    Nav2Config,
    NavigationResult,
    ResilientNav2Navigator,
    Ros2AdapterError,
    Ros2RobotAdapter,
    Ros2TopicObservationProvider,
)


class _Backend:
    def __init__(self, results: list[NavigationResult]) -> None:
        self.results = list(results)
        self.calls = []

    def navigate(self, waypoint, *, timeout_seconds, cancel_timeout_seconds):
        self.calls.append((waypoint.waypoint_id, timeout_seconds, cancel_timeout_seconds))
        return self.results.pop(0)


class _Provider:
    def __init__(self, observation: Observation) -> None:
        self.observation = observation
        self.closed = False

    def capture(self, waypoint, *, timeout_seconds):
        return self.observation

    def close(self):
        self.closed = True


@dataclass
class _Stamp:
    sec: int = 1792972800
    nanosec: int = 0


class Ros2Nav2Tests(unittest.TestCase):
    def setUp(self) -> None:
        config = load_site_config("configs/site.json")
        self.waypoint = waypoints_from_config(config)[0]

    def test_retry_policy_is_bounded_and_preserves_attempt_count(self):
        backend = _Backend([
            NavigationResult("FAILED", error="planner unavailable"),
            NavigationResult("SUCCEEDED"),
        ])
        sleeps: list[float] = []
        navigator = ResilientNav2Navigator(
            backend,
            Nav2Config(max_retries=1, retry_delay_seconds=0.25),
            sleep=sleeps.append,
        )
        result = navigator.navigate(self.waypoint)

        self.assertEqual(result.status, "SUCCEEDED")
        self.assertEqual(result.attempts, 2)
        self.assertEqual(sleeps, [0.25])
        self.assertEqual(len(backend.calls), 2)

    def test_cancelled_navigation_does_not_retry(self):
        backend = _Backend([NavigationResult("CANCELLED", error="operator cancelled")])
        navigator = ResilientNav2Navigator(backend, Nav2Config(max_retries=5), sleep=lambda _: None)

        result = navigator.navigate(self.waypoint)

        self.assertEqual(result.status, "CANCELLED")
        self.assertEqual(result.attempts, 1)
        self.assertEqual(len(backend.calls), 1)

    def test_robot_adapter_requires_matching_robot_observation_and_closes_provider(self):
        observation = Observation(
            sample_id="robot-sample-1",
            timestamp_utc="2026-10-26T00:00:00+00:00",
            source="robot",
            robot_id="go2-01",
            waypoint_id=self.waypoint.waypoint_id,
            device_id=self.waypoint.device_id,
            domain={"sensor_provenance": {
                "sensor_ids": ["rgb_camera"], "frame_id": "base_link/rgb_camera",
            }},
        )
        provider = _Provider(observation)
        adapter = Ros2RobotAdapter(
            ResilientNav2Navigator(_Backend([NavigationResult("SUCCEEDED")]), Nav2Config()),
            provider,
        )

        self.assertTrue(adapter.navigate(self.waypoint))
        captured = adapter.capture(self.waypoint, 1)
        self.assertEqual(captured.source, "robot")
        self.assertEqual(adapter.state, "COMPLETED")
        adapter.close()
        self.assertTrue(provider.closed)

    def test_robot_adapter_rejects_observation_from_another_source(self):
        observation = Observation(
            sample_id="wrong-source",
            timestamp_utc="2026-10-26T00:00:00+00:00",
            source="synthetic_simulation",
            robot_id="go2-01",
            waypoint_id=self.waypoint.waypoint_id,
            device_id=self.waypoint.device_id,
        )
        adapter = Ros2RobotAdapter(
            ResilientNav2Navigator(_Backend([NavigationResult("SUCCEEDED")]), Nav2Config()),
            _Provider(observation),
        )
        adapter.navigate(self.waypoint)
        with self.assertRaisesRegex(Ros2AdapterError, "source"):
            adapter.capture(self.waypoint, 1)
        self.assertEqual(adapter.state, "FAILED")

    def test_topic_message_conversion_preserves_presence_flags_and_provenance(self):
        provider = Ros2TopicObservationProvider.__new__(Ros2TopicObservationProvider)
        provider._robot_id = "go2-01"
        provider._source = "robot"
        message = type("Message", (), {
            "stamp": _Stamp(),
            "sample_id": "ros-sample-1",
            "source": "robot",
            "robot_id": "go2-01",
            "waypoint_id": self.waypoint.waypoint_id,
            "device_id": self.waypoint.device_id,
            "has_pressure": True,
            "pressure_mpa": 0.8,
            "has_temperature": False,
            "temperature_c": 0.0,
            "has_ambient_temperature": True,
            "ambient_temperature_c": 25.0,
            "has_door_state": False,
            "cabinet_door_closed": False,
            "has_leak_state": True,
            "leak_detected": False,
            "model_version": "model-1",
            "calibration_version": "cal-1",
            "quality_flags_json": json.dumps(["LOW_LIGHT"]),
            "has_inference_latency": True,
            "inference_latency_ms": 8.0,
            "sensor_ids_json": json.dumps(["rgb_camera", "thermal_camera"]),
            "frame_id": "base_link/rgb_camera",
            "domain_json": json.dumps({"temperature_semantics": "measured"}),
        })()

        observation = provider._convert(message, self.waypoint)

        self.assertEqual(observation.pressure_mpa, 0.8)
        self.assertIsNone(observation.temperature_c)
        self.assertEqual(observation.quality_flags, ["LOW_LIGHT"])
        self.assertEqual(observation.model_version, "model-1")
        self.assertEqual(
            observation.domain["sensor_provenance"]["sensor_ids"],
            ["rgb_camera", "thermal_camera"],
        )
        self.assertEqual(observation.domain["temperature_semantics"], "measured")

    def test_invalid_nav2_configuration_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "MAX_RETRIES"):
            Nav2Config(max_retries=11).validate()
        with self.assertRaisesRegex(ValueError, "map_frame"):
            Nav2Config(map_frame="map/base_link").validate()


if __name__ == "__main__":
    unittest.main()
