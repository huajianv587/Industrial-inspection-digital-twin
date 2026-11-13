from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from inspection_system import cli
from inspection_system.perception.model_runtime import (
    MODEL_INPUT_SCHEMA_VERSION,
    MODEL_OUTPUT_SCHEMA_VERSION,
    ModelManifest,
    ModelRuntime,
    ModelRuntimeError,
    load_model_manifest,
    validate_model_input,
)


class ModelRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="model-runtime-test-")
        self.root = Path(self.temp.name)
        self.artifact = self.root / "inspection-model.bin"
        self.artifact.write_bytes(b"model weights used only by the contract test")
        self.manifest_path = self.root / "model.json"
        self.write_manifest()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def manifest_data(self) -> dict:
        return {
            "schema_version": 1,
            "model_id": "inspection-baseline",
            "model_version": "1.2.3",
            "task": "inspection_observation",
            "runtime": {
                "name": "python",
                "version": "3.12.0",
                "entrypoint": "model_adapter:build_predictor",
            },
            "input_schema": MODEL_INPUT_SCHEMA_VERSION,
            "output_schema": MODEL_OUTPUT_SCHEMA_VERSION,
            "artifact": {
                "path": self.artifact.name,
                "sha256": hashlib.sha256(self.artifact.read_bytes()).hexdigest(),
                "size_bytes": self.artifact.stat().st_size,
            },
        }

    def write_manifest(self, value: dict | None = None) -> None:
        self.manifest_path.write_text(
            json.dumps(value or self.manifest_data(), ensure_ascii=False),
            encoding="utf-8",
        )

    @staticmethod
    def input_payload() -> dict:
        return {
            "schema_version": MODEL_INPUT_SCHEMA_VERSION,
            "sample_id": "sample-001",
            "timestamp_utc": "2026-10-26T00:00:00+00:00",
            "waypoint_id": "WP_01_PIPE",
            "device_id": "PIPE-01",
            "sensor_provenance": {
                "sensor_ids": ["rgb_camera"],
                "frame_id": "base_link/rgb_camera",
            },
            "features": {"edge_score": 0.42, "crop": {"width": 640}},
        }

    @staticmethod
    def output_payload(sample_id: str = "sample-001", model_version: str = "1.2.3") -> dict:
        return {
            "schema_version": MODEL_OUTPUT_SCHEMA_VERSION,
            "sample_id": sample_id,
            "model_version": model_version,
            "calibration_version": None,
            "pressure_mpa": None,
            "temperature_c": 43.5,
            "ambient_temperature_c": 25.0,
            "cabinet_door_closed": None,
            "leak_detected": False,
            "sensor_confidence": {"rgb_camera": 0.91},
            "quality_flags": [],
            "inference_latency_ms": 12.5,
        }

    def test_manifest_validates_artifact_digest_and_manifest_digest(self) -> None:
        manifest = load_model_manifest(self.manifest_path, runtime_version="3.12.0")

        self.assertEqual(manifest.model_id, "inspection-baseline")
        self.assertEqual(manifest.model_version, "1.2.3")
        self.assertEqual(manifest.artifact.path, self.artifact.resolve())
        self.assertEqual(len(manifest.manifest_sha256), 64)

    def test_artifact_tampering_fails_closed(self) -> None:
        self.artifact.write_bytes(b"x" * self.artifact.stat().st_size)

        with self.assertRaisesRegex(ModelRuntimeError, "SHA-256"):
            load_model_manifest(self.manifest_path, runtime_version="3.12.0")

    def test_manifest_rejects_runtime_and_schema_mismatch(self) -> None:
        manifest = self.manifest_data()
        manifest["runtime"]["version"] = "9.9.9"
        self.write_manifest(manifest)
        with self.assertRaisesRegex(ModelRuntimeError, "runtime version mismatch"):
            load_model_manifest(self.manifest_path, runtime_version="3.12.0")

        manifest = self.manifest_data()
        manifest["output_schema"] = "other/v1"
        self.write_manifest(manifest)
        with self.assertRaisesRegex(ModelRuntimeError, "output schema"):
            load_model_manifest(self.manifest_path, runtime_version="3.12.0")

    def test_relative_artifact_escape_and_symlink_are_rejected(self) -> None:
        outside = self.root.parent / "outside-model.bin"
        outside.write_bytes(b"outside")
        self.addCleanup(outside.unlink, missing_ok=True)
        manifest = self.manifest_data()
        manifest["artifact"] = {
            "path": "../outside-model.bin",
            "sha256": hashlib.sha256(outside.read_bytes()).hexdigest(),
            "size_bytes": outside.stat().st_size,
        }
        self.write_manifest(manifest)
        with self.assertRaisesRegex(ModelRuntimeError, "inside the model manifest"):
            load_model_manifest(self.manifest_path, runtime_version="3.12.0")

        symlink = self.root / "model-link.bin"
        try:
            os.symlink(self.artifact, symlink)
        except (OSError, NotImplementedError):
            self.skipTest("symbolic links are unavailable in this filesystem")
        manifest = self.manifest_data()
        manifest["artifact"]["path"] = symlink.name
        self.write_manifest(manifest)
        with self.assertRaisesRegex(ModelRuntimeError, "symbolic link"):
            load_model_manifest(self.manifest_path, runtime_version="3.12.0")

    def test_input_rejects_unknown_fields_and_non_utc_timestamp(self) -> None:
        payload = self.input_payload()
        payload["unexpected"] = True
        with self.assertRaisesRegex(ModelRuntimeError, "model input fields"):
            validate_model_input(payload)

        payload = self.input_payload()
        payload["timestamp_utc"] = "2026-10-26T08:00:00+08:00"
        with self.assertRaisesRegex(ModelRuntimeError, "normalized to UTC"):
            validate_model_input(payload)

    def test_inference_validates_output_and_propagates_manifest_version(self) -> None:
        def loader(_entrypoint: str):
            return lambda _artifact: lambda _payload: self.output_payload()

        runtime = ModelRuntime.load(
            self.manifest_path,
            runtime_version="3.12.0",
            entrypoint_loader=loader,
        )
        output = runtime.infer(self.input_payload())

        self.assertEqual(output["model_version"], "1.2.3")
        self.assertEqual(output["sample_id"], "sample-001")

    def test_inference_failure_has_no_fallback(self) -> None:
        def loader(_entrypoint: str):
            def build(_artifact: Path):
                def predict(_payload):
                    raise RuntimeError("weights unavailable")

                return predict

            return build

        runtime = ModelRuntime.load(
            self.manifest_path,
            runtime_version="3.12.0",
            entrypoint_loader=loader,
        )
        with self.assertRaisesRegex(ModelRuntimeError, "no fallback"):
            runtime.infer(self.input_payload())

    def test_invalid_model_output_is_rejected(self) -> None:
        def loader(_entrypoint: str):
            return lambda _artifact: lambda _payload: {
                **self.output_payload(),
                "model_version": "9.9.9",
            }

        runtime = ModelRuntime.load(
            self.manifest_path,
            runtime_version="3.12.0",
            entrypoint_loader=loader,
        )
        with self.assertRaisesRegex(ModelRuntimeError, "model_version"):
            runtime.infer(self.input_payload())

    def test_missing_runtime_entrypoint_fails_closed(self) -> None:
        with self.assertRaisesRegex(ModelRuntimeError, "entrypoint cannot be loaded"):
            ModelRuntime.load(
                self.manifest_path,
                runtime_version="3.12.0",
            )

    def test_cli_validation_reports_manifest_and_artifact_provenance(self) -> None:
        manifest = load_model_manifest(self.manifest_path, runtime_version="3.12.0")
        fake_runtime = ModelRuntime(
            manifest=manifest,
            predictor=lambda _payload: self.output_payload(),
        )
        stdout = StringIO()
        with patch("inspection_system.cli.ModelRuntime.load", return_value=fake_runtime), \
                redirect_stdout(stdout):
            result = cli.main(["validate-model", "--manifest", str(self.manifest_path)])

        self.assertEqual(result, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["model_id"], "inspection-baseline")
        self.assertEqual(payload["artifact_sha256"], manifest.artifact.sha256)
        self.assertEqual(payload["inference"], None)

    def test_cli_returns_nonzero_for_unavailable_runtime(self) -> None:
        stderr = StringIO()
        with patch(
            "inspection_system.cli.ModelRuntime.load",
            side_effect=ModelRuntimeError("runtime unavailable"),
        ), redirect_stderr(stderr):
            result = cli.main(["validate-model", "--manifest", str(self.manifest_path)])

        self.assertEqual(result, 2)
        self.assertIn("runtime unavailable", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
