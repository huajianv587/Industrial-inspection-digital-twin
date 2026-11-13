from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from inspection_system.platform.artifact_storage import LocalArtifactStorage
from inspection_system.platform.artifact_store import store_artifact_bytes
from inspection_system.platform.db import Base, create_database
from inspection_system.platform.entities import ArtifactRecord, MissionRecord
from inspection_system.platform.result_service import (
    ResultValidationError,
    _validate_artifacts,
)


class _TrackingStorage:
    def __init__(self, root: Path):
        self.inner = LocalArtifactStorage(root, 32 * 1024 * 1024)
        self.max_bytes = self.inner.max_bytes
        self.read_digests: list[str] = []
        self.verified_digests: list[str] = []

    def put_bytes(self, run_id: str, digest: str, content: bytes) -> str:
        return self.inner.put_bytes(run_id, digest, content)

    def read_bytes(self, reference: str) -> bytes:
        self.read_digests.append(Path(reference).name)
        return self.inner.read_bytes(reference)

    def validate_reference(self, reference: str, run_id: str, digest: str) -> bool:
        return self.inner.validate_reference(reference, run_id, digest)

    def verify_artifact(self, reference: str, run_id: str, digest: str, size: int) -> bool:
        self.verified_digests.append(Path(reference).name)
        return self.inner.verify_artifact(reference, run_id, digest, size)


class ResultArtifactValidationTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        root = Path(self.temp_dir.name)
        self.engine, self.factory = create_database("sqlite://", environment="test")
        Base.metadata.create_all(self.engine)
        self.addCleanup(self.engine.dispose)
        self.storage = _TrackingStorage(root / "artifacts")
        self.run_id = "RUN-STREAM-001"
        self.artifact_name = "WP_01_PIPE__camera_frame.bin"
        self.inspection_run = {
            "run_id": self.run_id,
            "started_at_utc": "2026-10-21T00:00:00Z",
            "finished_at_utc": "2026-10-21T01:00:00Z",
            "results": [{
                "work_order": None,
                "observation": {
                    "domain": {
                        "sensor_provenance": {
                            "sensor_ids": ["rgb_camera"],
                            "artifacts": [{
                                "name": self.artifact_name,
                                "sensor_id": "rgb_camera",
                                "media_type": "application/octet-stream",
                                "timestamp_utc": "2026-10-21T00:30:00Z",
                            }],
                        },
                    },
                },
            }],
        }
        contents = {
            "inspection_run.json": json.dumps(self.inspection_run).encode("utf-8"),
            "work_orders.json": b"[]",
            "inspection_report.md": f"Inspection run {self.run_id}\n".encode("utf-8"),
            self.artifact_name: b"\x00" * (2 * 1024 * 1024),
        }
        self.descriptors = []
        with self.factory() as session:
            session.add(MissionRecord(
                run_id=self.run_id,
                site_id="SITE-TEST",
                robot_id="ROBOT-TEST",
                execution_backend="slurm",
                status="RUNNING",
                seed=7,
                manifest_json="{}",
                request_hash="0" * 64,
            ))
            session.flush()
            for name, content in contents.items():
                record = store_artifact_bytes(
                    session, self.storage, self.run_id, name, content, "isaac_sim")
                self.descriptors.append({
                    "name": name,
                    "sha256": record.sha256,
                    "size_bytes": record.size_bytes,
                })
            session.commit()

    def test_binary_artifacts_are_stream_verified_not_loaded(self):
        with self.factory() as session:
            _validate_artifacts(
                session, self.storage, self.run_id, "isaac_sim",
                self.descriptors, self.inspection_run,
            )

        required_digests = [
            item["sha256"] for item in self.descriptors
            if item["name"] != self.artifact_name
        ]
        binary_digest = next(
            item["sha256"] for item in self.descriptors
            if item["name"] == self.artifact_name
        )
        self.assertCountEqual(self.storage.read_digests, required_digests)
        self.assertEqual(self.storage.verified_digests, [binary_digest])

    def test_corrupt_binary_artifact_is_rejected_by_stream_verification(self):
        with self.factory() as session:
            record = session.query(ArtifactRecord).filter_by(
                run_id=self.run_id, name=self.artifact_name).one()
            Path(record.storage_path).write_bytes(b"\x01" * record.size_bytes)

            with self.assertRaisesRegex(ResultValidationError, "integrity check"):
                _validate_artifacts(
                    session, self.storage, self.run_id, "isaac_sim",
                    self.descriptors, self.inspection_run,
                )

    def test_oversized_required_metadata_is_rejected_before_storage_reads(self):
        descriptors = [dict(item) for item in self.descriptors]
        report = next(item for item in descriptors
                      if item["name"] == "inspection_report.md")
        report["size_bytes"] = 2 * 1024 * 1024 + 1

        with self.factory() as session:
            with self.assertRaisesRegex(ResultValidationError, "exceeds its"):
                _validate_artifacts(
                    session, self.storage, self.run_id, "isaac_sim",
                    descriptors, self.inspection_run,
                )

        self.assertEqual(self.storage.read_digests, [])
        self.assertEqual(self.storage.verified_digests, [])

    def test_binary_artifact_without_observation_reference_is_rejected(self):
        inspection_run = copy.deepcopy(self.inspection_run)
        inspection_run["results"][0]["observation"]["domain"][
            "sensor_provenance"]["artifacts"] = []

        with self.factory() as session:
            with self.assertRaisesRegex(ResultValidationError, "no observation reference"):
                _validate_artifacts(
                    session, self.storage, self.run_id, "isaac_sim",
                    self.descriptors, inspection_run,
                )

        self.assertEqual(self.storage.read_digests, [])
        self.assertEqual(self.storage.verified_digests, [])


if __name__ == "__main__":
    unittest.main()
