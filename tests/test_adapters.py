from __future__ import annotations

from datetime import datetime, timezone
import json
import unittest

from inspection_system.adapters.simulation import SimulatedRobotAdapter
from inspection_system.config import load_site_config, waypoints_from_config
from inspection_system.mission.orchestrator import MissionOrchestrator
from inspection_system.models import Observation
from inspection_system.platform.eam import build_eam_request
from inspection_system.platform.entities import WorkOrderRecord


class _RobotAdapter:
    source = "robot"

    def __init__(self, *, observation_source: str = "robot"):
        self.observation_source = observation_source

    def navigate(self, waypoint):
        return True

    def capture(self, waypoint, index):
        return Observation(
            sample_id=f"sample-{index}",
            timestamp_utc=datetime.now(timezone.utc).isoformat(),
            source=self.observation_source,
            robot_id="robot-test",
            waypoint_id=waypoint.waypoint_id,
            device_id=waypoint.device_id,
        )


class RobotAdapterContractTests(unittest.TestCase):
    def setUp(self):
        config = load_site_config("configs/site.json")
        self.site_id = config["site_id"]
        self.robot_id = config["robot"]["robot_id"]
        self.waypoints = waypoints_from_config(config)[:1]

    def test_orchestrator_accepts_structural_adapter_and_preserves_declared_source(self):
        adapter = _RobotAdapter()
        run = MissionOrchestrator(
            self.site_id, "robot-test", self.waypoints, adapter=adapter,
        ).run()
        self.assertEqual(run.source, "robot")
        self.assertEqual(run.results[0].observation.source, "robot")

    def test_orchestrator_rejects_observation_with_mismatched_source(self):
        adapter = _RobotAdapter(observation_source="synthetic_simulation")
        run = MissionOrchestrator(
            self.site_id, "robot-test", self.waypoints, adapter=adapter,
        ).run()
        self.assertEqual(run.status, "COMPLETED_WITH_ERRORS")
        self.assertIsNone(run.results[0].observation)
        self.assertIn("source does not match", run.results[0].error)

    def test_simulated_adapter_remains_explicitly_synthetic(self):
        self.assertEqual(SimulatedRobotAdapter("robot-test").source, "synthetic_simulation")


class EamApprovalBoundaryTests(unittest.TestCase):
    @staticmethod
    def record(**overrides):
        values = {
            "ticket_id": "TICKET-001",
            "run_id": "RUN-0000000000000001",
            "severity": "WARNING",
            "review_status": "REVIEWED",
            "payload_json": json.dumps({"device_id": "PUMP-01"}),
            "reviewed_by": "reviewer-1",
            "review_decision": "ACKNOWLEDGED",
            "review_comment": "Dispatch maintenance review.",
            "reviewed_at": datetime.now(timezone.utc),
        }
        values.update(overrides)
        return WorkOrderRecord(**values)

    def test_eam_request_requires_explicit_recorded_acknowledgement(self):
        for overrides in (
            {"review_status": "PENDING", "review_decision": None},
            {"review_status": "DISMISSED", "review_decision": "DISMISSED"},
            {"reviewed_by": None},
            {"reviewed_at": None},
        ):
            with self.subTest(overrides=overrides):
                with self.assertRaisesRegex(ValueError, "human acknowledgement"):
                    build_eam_request(self.record(**overrides))

    def test_approved_request_has_stable_idempotency_key_and_review_provenance(self):
        request = build_eam_request(self.record())
        self.assertEqual(request.idempotency_key, "TICKET-001")
        self.assertEqual(request.approval_decision, "ACKNOWLEDGED")
        self.assertEqual(request.reviewed_by, "reviewer-1")
        self.assertEqual(json.loads(request.payload_json), {"device_id": "PUMP-01"})


if __name__ == "__main__":
    unittest.main()
