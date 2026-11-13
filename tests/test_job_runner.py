from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from inspection_system.config import load_site_config
from inspection_system.platform.job_runner import run_job
from inspection_system.platform.logging_config import JsonLogFormatter


def canonical_sha256(value: object) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class SyntheticJobRunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="job-runner-test-")
        self.root = Path(self.temp.name)
        self.config = load_site_config("configs/site.json")
        self.manifest = {
            "schema_version": 1,
            "run_id": "RUN-0000000000000001",
            "site_id": self.config["site_id"],
            "robot_id": self.config["robot"]["robot_id"],
            "waypoint_ids": [item["waypoint_id"] for item in self.config["waypoints"]],
            "seed": 42,
            "source": "synthetic_simulation",
            "config_sha256": canonical_sha256(self.config),
            "site_config": self.config,
        }
        self.manifest_path = self.root / "mission.json"
        self.write_manifest()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def write_manifest(self, value: object | None = None) -> None:
        self.manifest_path.write_text(
            json.dumps(value if value is not None else self.manifest), encoding="utf-8"
        )

    def test_valid_manifest_builds_bundle_with_structured_run_context(self) -> None:
        with self.assertLogs("inspection_system.platform.job_runner", level="INFO") as captured:
            bundle = run_job(self.manifest_path, self.root / "output")

        self.assertTrue(bundle.is_file())
        start = json.loads(JsonLogFormatter().format(captured.records[0]))
        finish = json.loads(JsonLogFormatter().format(captured.records[-1]))
        self.assertEqual(start["run_id"], self.manifest["run_id"])
        self.assertEqual(start["execution_backend"], "slurm")
        self.assertEqual(finish["result_status"], "COMPLETED")

    def test_invalid_manifest_identity_seed_and_checksum_fail_before_execution(self) -> None:
        cases = [
            ({**self.manifest, "run_id": "not-a-run-id"}, "run_id"),
            ({**self.manifest, "site_id": "OTHER-SITE"}, "site_id"),
            ({**self.manifest, "robot_id": "OTHER-ROBOT"}, "robot_id"),
            ({**self.manifest, "seed": True}, "seed"),
            ({**self.manifest, "config_sha256": "0" * 64}, "checksum"),
        ]
        for manifest, message in cases:
            with self.subTest(message=message):
                output = self.root / f"output-{message}"
                self.write_manifest(manifest)
                with self.assertRaisesRegex(ValueError, message):
                    run_job(self.manifest_path, output)
                self.assertFalse(output.exists())

    def test_manifest_must_use_schema_integer_not_boolean(self) -> None:
        self.write_manifest({**self.manifest, "schema_version": True})
        with self.assertRaisesRegex(ValueError, "manifest version"):
            run_job(self.manifest_path, self.root / "output")


if __name__ == "__main__":
    unittest.main()
