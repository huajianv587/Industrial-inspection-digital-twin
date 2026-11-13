from __future__ import annotations

import unittest
from unittest.mock import patch

from scripts.release_audit import _external_checks, overall_status


class ReleaseAuditTests(unittest.TestCase):
    def test_local_checks_can_pass_while_external_validation_remains_open(self):
        checks = [
            {"kind": "local", "status": "PASSED"},
            {"kind": "synthetic", "status": "PASSED"},
            {"kind": "external", "status": "NOT_VALIDATED"},
        ]
        self.assertEqual(
            overall_status(checks),
            "LOCAL_VERIFIED_EXTERNAL_VALIDATION_REQUIRED",
        )

    def test_failed_local_check_blocks_release(self):
        checks = [
            {"kind": "local", "status": "FAILED"},
            {"kind": "external", "status": "READY_TO_RUN"},
        ]
        self.assertEqual(overall_status(checks), "LOCAL_CHECKS_FAILED")

    def test_failed_synthetic_check_blocks_release(self):
        checks = [
            {"kind": "local", "status": "PASSED"},
            {"kind": "synthetic", "status": "FAILED"},
            {"kind": "external", "status": "NOT_VALIDATED"},
        ]
        self.assertEqual(overall_status(checks), "LOCAL_CHECKS_FAILED")

    def test_ready_to_run_external_check_is_not_a_release_pass(self):
        checks = [
            {"kind": "local", "status": "PASSED"},
            {"kind": "external", "status": "READY_TO_RUN"},
        ]
        self.assertEqual(
            overall_status(checks),
            "LOCAL_VERIFIED_EXTERNAL_VALIDATION_REQUIRED",
        )

    def test_external_credential_detection_does_not_claim_validation(self):
        with patch("scripts.release_audit.ROOT") as root:
            root.__truediv__.side_effect = lambda name: root
            root.is_file.return_value = True
            root.__str__.return_value = "/tmp/project"
            with patch("scripts.release_audit._compose_command", return_value=["docker", "compose"]):
                checks = _external_checks()

        statuses = {item["id"]: item["status"] for item in checks}
        self.assertEqual(statuses["supabase_auth_e2e"], "READY_TO_RUN")
        self.assertEqual(statuses["supabase_storage_io"], "READY_TO_RUN")
        self.assertEqual(statuses["compose_runtime"], "READY_TO_RUN")
        self.assertEqual(statuses["slurm_isaac_ros2"], "NOT_VALIDATED")
        self.assertEqual(statuses["field_robot_eam"], "NOT_VALIDATED")


if __name__ == "__main__":
    unittest.main()
