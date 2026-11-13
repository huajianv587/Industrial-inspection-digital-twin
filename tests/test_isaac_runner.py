from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import platform
from pathlib import Path
import tarfile
import tempfile
import unittest

from inspection_system.config import load_site_config, waypoints_from_config
from inspection_system.models import Observation
from inspection_system.perception.model_runtime import (
    MODEL_INPUT_SCHEMA_VERSION,
    MODEL_OUTPUT_SCHEMA_VERSION,
)
from inspection_system.platform.isaac_runner import (
    IsaacRunnerError,
    WaypointArtifact,
    WaypointCapture,
    load_isaac_manifest,
    run_isaac_job,
)
from inspection_system.platform.logging_config import JsonLogFormatter
from inspection_system.platform.result_bundle import read_result_bundle
from inspection_system.platform.settings import Settings
from inspection_system.platform.slurm import SlurmClient


def canonical_json(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")


class FakeSimulationApp:
    def __init__(self) -> None:
        self.closed = False
        self.updates = 0

    def update(self) -> None:
        self.updates += 1

    def close(self) -> None:
        self.closed = True


class FakeIsaacAdapter:
    def __init__(self, _app, _manifest, _waypoints, *, observation_source="isaac_sim"):
        self.observation_source = observation_source
        self.started = False
        self.closed = False
        self.seeds: list[tuple[int, int]] = []

    def start(self) -> None:
        self.started = True

    def inspect_waypoint(self, waypoint, *, seed: int, index: int) -> WaypointCapture:
        self.seeds.append((seed, index))
        observation = Observation(
            sample_id="adapter-sample-id",
            timestamp_utc=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            source=self.observation_source,
            robot_id="unitree-sim-01",
            waypoint_id=waypoint.waypoint_id,
            device_id=waypoint.device_id,
            pressure_mpa=None,
            temperature_c=43.0,
            ambient_temperature_c=26.5,
            cabinet_door_closed=None,
            leak_detected=None,
            sensor_confidence={"rgb_camera": 0.91},
            domain={
                "sensor_provenance": {
                    "sensor_ids": ["rgb_camera"],
                    "frame_id": "base_link/rgb_camera",
                },
                "temperature_semantics": "simulated_proxy",
            },
        )
        return WaypointCapture("SUCCEEDED", "COMPLETED", observation)

    def close(self) -> None:
        self.closed = True


class ModelInputIsaacAdapter(FakeIsaacAdapter):
    def inspect_waypoint(self, waypoint, *, seed: int, index: int) -> WaypointCapture:
        capture = super().inspect_waypoint(waypoint, seed=seed, index=index)
        capture.observation.domain["model_input"] = {
            "schema_version": MODEL_INPUT_SCHEMA_VERSION,
            "features": {"edge_score": 0.42, "waypoint_index": index},
        }
        return capture


class IsaacRunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="isaac-runner-test-")
        self.root = Path(self.temp.name)
        self.asset = self.root / "go2.usd"
        self.asset.write_bytes(b"test asset placeholder")
        self.python = self.root / "python.sh"
        self.python.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        self.python.chmod(self.python.stat().st_mode | 0o111)
        self.config = load_site_config("configs/site.json")
        self.manifest_path = self.root / "mission.json"
        self.write_manifest()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def make_manifest(self) -> dict:
        return {
            "schema_version": 1,
            "run_id": "RUN-0000000000000001",
            "site_id": self.config["site_id"],
            "robot_id": self.config["robot"]["robot_id"],
            "waypoint_ids": [item["waypoint_id"] for item in self.config["waypoints"]],
            "seed": 42,
            "source": "isaac_sim",
            "config_sha256": hashlib.sha256(canonical_json(self.config)).hexdigest(),
            "site_config": self.config,
            "simulator": {
                "expected_version": "1.2.3",
                "robot_usd_path": str(self.asset),
                "python_path": str(self.python),
                "adapter_entrypoint": "inspection_system.adapters.test_isaac:create_adapter",
            },
        }

    def write_manifest(self, manifest: dict | None = None) -> None:
        self.manifest_path.write_text(
            json.dumps(manifest or self.make_manifest(), ensure_ascii=False), encoding="utf-8"
        )

    def write_model_manifest(self) -> tuple[Path, dict]:
        artifact = self.root / "inspection-model.bin"
        artifact.write_bytes(b"model weights used by the Isaac integration test")
        manifest = {
            "schema_version": 1,
            "model_id": "inspection-baseline",
            "model_version": "1.2.3",
            "task": "inspection_observation",
            "runtime": {
                "name": "python",
                "version": platform.python_version(),
                "entrypoint": "model_adapter:build_predictor",
            },
            "input_schema": MODEL_INPUT_SCHEMA_VERSION,
            "output_schema": MODEL_OUTPUT_SCHEMA_VERSION,
            "artifact": {
                "path": artifact.name,
                "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
                "size_bytes": artifact.stat().st_size,
            },
        }
        model_manifest_path = self.root / "model.json"
        model_manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        return model_manifest_path, manifest

    def add_model_config(self, manifest: dict) -> tuple[Path, dict]:
        model_manifest_path, model_manifest = self.write_model_manifest()
        artifact = self.root / model_manifest["artifact"]["path"]
        manifest["simulator"]["model"] = {
            "manifest_path": str(model_manifest_path),
            "manifest_sha256": hashlib.sha256(model_manifest_path.read_bytes()).hexdigest(),
            "artifact_sha256": model_manifest["artifact"]["sha256"],
            "model_id": model_manifest["model_id"],
            "model_version": model_manifest["model_version"],
        }
        return model_manifest_path, model_manifest

    @staticmethod
    def model_output(payload: dict, *, temperature_c: float = 88.0) -> dict:
        return {
            "schema_version": MODEL_OUTPUT_SCHEMA_VERSION,
            "sample_id": payload["sample_id"],
            "model_version": "1.2.3",
            "calibration_version": "calibration-2026-10",
            "pressure_mpa": 0.31,
            "temperature_c": temperature_c,
            "ambient_temperature_c": 26.0,
            "cabinet_door_closed": True,
            "leak_detected": False,
            "sensor_confidence": {"rgb_camera": 0.99},
            "quality_flags": ["MODEL_OK"],
            "inference_latency_ms": 4.5,
        }

    def test_manifest_validates_frozen_config_assets_and_order(self) -> None:
        validated = load_isaac_manifest(self.manifest_path)
        self.assertEqual(validated.expected_version, "1.2.3")
        self.assertEqual(validated.robot_usd_path, self.asset)
        self.assertEqual(validated.python_path, self.python)
        self.assertEqual(
            [item.waypoint_id for item in validated.waypoints],
            [item.waypoint_id for item in waypoints_from_config(self.config)],
        )

        manifest = self.make_manifest()
        manifest["waypoint_ids"] = list(reversed(manifest["waypoint_ids"]))
        self.write_manifest(manifest)
        with self.assertRaisesRegex(IsaacRunnerError, "waypoint order"):
            load_isaac_manifest(self.manifest_path)

    def test_missing_robot_asset_fails_before_runtime_start(self) -> None:
        manifest = self.make_manifest()
        manifest["simulator"]["robot_usd_path"] = str(self.root / "missing.usd")
        self.write_manifest(manifest)
        with self.assertRaisesRegex(IsaacRunnerError, "asset is unavailable"):
            load_isaac_manifest(self.manifest_path)

    def test_runtime_version_mismatch_closes_application_without_adapter(self) -> None:
        app = FakeSimulationApp()
        factory_calls: list[bool] = []
        with self.assertRaisesRegex(IsaacRunnerError, "version mismatch"):
            run_isaac_job(
                self.manifest_path,
                self.root / "output",
                app_factory=lambda: app,
                version_reader=lambda: "9.9.9",
                adapter_factory=lambda *_args: factory_calls.append(True),
            )
        self.assertTrue(app.closed)
        self.assertEqual(factory_calls, [])
        self.assertFalse((self.root / "output" / "result_bundle.zip").exists())

    def test_valid_runtime_builds_provenance_checked_result_bundle(self) -> None:
        app = FakeSimulationApp()
        adapters: list[FakeIsaacAdapter] = []

        def create_adapter(*args):
            adapter = FakeIsaacAdapter(*args)
            adapters.append(adapter)
            return adapter

        bundle_path = run_isaac_job(
            self.manifest_path,
            self.root / "output",
            app_factory=lambda: app,
            version_reader=lambda: "1.2.3",
            adapter_factory=create_adapter,
        )
        bundle_manifest, inspection_run, _artifacts = read_result_bundle(bundle_path)
        self.assertEqual(bundle_manifest["source"], "isaac_sim")
        self.assertEqual(bundle_manifest["software_version"], "isaac-sim/1.2.3")
        self.assertEqual(inspection_run["source"], "isaac_sim")
        self.assertEqual(inspection_run["status"], "COMPLETED")
        self.assertEqual(len(inspection_run["results"]), len(self.config["waypoints"]))
        for index, item in enumerate(inspection_run["results"], start=1):
            self.assertIsNone(item["observation"]["pressure_mpa"])
            self.assertEqual(item["observation"]["source"], "isaac_sim")
            self.assertEqual(item["observation"]["sample_id"],
                             f"RUN-0000000000000001-{index:03d}-{item['waypoint_id']}")
            provenance = item["observation"]["domain"]["simulation_provenance"]
            self.assertEqual(provenance["runtime_version"], "1.2.3")
            self.assertEqual(provenance["seed"], 42)
        self.assertEqual(adapters[0].seeds, [(42, index) for index in range(1, 4)])
        self.assertTrue(adapters[0].started)
        self.assertTrue(adapters[0].closed)
        self.assertTrue(app.closed)

    def test_sensor_artifacts_are_linked_to_waypoint_provenance(self) -> None:
        app = FakeSimulationApp()
        frame_path = self.root / "rgb-frame.bin"
        frame_content = b"sample sensor frame"
        frame_path.write_bytes(frame_content)

        class ArtifactAdapter(FakeIsaacAdapter):
            def inspect_waypoint(self, waypoint, *, seed: int, index: int):
                capture = super().inspect_waypoint(waypoint, seed=seed, index=index)
                if index != 1:
                    return capture
                artifact = WaypointArtifact(
                    name="rgb_frame.bin",
                    sensor_id="rgb_camera",
                    media_type="application/octet-stream",
                    timestamp_utc=capture.observation.timestamp_utc,
                    path=frame_path,
                )
                return WaypointCapture(
                    capture.navigation_status,
                    capture.inspection_status,
                    capture.observation,
                    capture.error,
                    (artifact,),
                )

        bundle_path = run_isaac_job(
            self.manifest_path,
            self.root / "artifact-output",
            app_factory=lambda: app,
            version_reader=lambda: "1.2.3",
            adapter_factory=lambda *args: ArtifactAdapter(*args),
        )
        manifest, inspection_run, artifacts = read_result_bundle(bundle_path)
        artifact_name = f"{self.config['waypoints'][0]['waypoint_id']}__rgb_frame.bin"
        observation = inspection_run["results"][0]["observation"]
        artifact_ref = observation["domain"]["sensor_provenance"]["artifacts"][0]

        self.assertEqual(artifact_ref["name"], artifact_name)
        self.assertEqual(artifact_ref["sensor_id"], "rgb_camera")
        self.assertEqual(artifacts[artifact_name], frame_content)
        self.assertIn(artifact_name, {item["name"] for item in manifest["artifacts"]})

    def test_configured_model_overrides_observation_and_emits_provenance(self) -> None:
        manifest = self.make_manifest()
        self.add_model_config(manifest)
        self.write_manifest(manifest)
        app = FakeSimulationApp()

        def loader(_entrypoint):
            return lambda _artifact: lambda payload: self.model_output(payload)

        bundle_path = run_isaac_job(
            self.manifest_path,
            self.root / "model-output",
            app_factory=lambda: app,
            version_reader=lambda: "1.2.3",
            adapter_factory=lambda *args: ModelInputIsaacAdapter(*args),
            model_entrypoint_loader=loader,
        )
        _bundle_manifest, inspection_run, _artifacts = read_result_bundle(bundle_path)
        observation = inspection_run["results"][0]["observation"]

        self.assertEqual(observation["temperature_c"], 88.0)
        self.assertEqual(observation["pressure_mpa"], 0.31)
        self.assertEqual(observation["model_version"], "1.2.3")
        self.assertNotIn("model_input", observation["domain"])
        self.assertEqual(observation["domain"]["model_provenance"], {
            "model_id": "inspection-baseline",
            "model_version": "1.2.3",
            "manifest_sha256": manifest["simulator"]["model"]["manifest_sha256"],
            "artifact_sha256": manifest["simulator"]["model"]["artifact_sha256"],
            "input_schema": MODEL_INPUT_SCHEMA_VERSION,
            "output_schema": MODEL_OUTPUT_SCHEMA_VERSION,
        })

    def test_model_digest_mismatch_fails_before_simulation_app_starts(self) -> None:
        for mismatch in ("manifest_sha256", "artifact_sha256"):
            with self.subTest(mismatch=mismatch):
                manifest = self.make_manifest()
                self.add_model_config(manifest)
                manifest["simulator"]["model"][mismatch] = "0" * 64
                self.write_manifest(manifest)
                app_factory_calls: list[bool] = []

                with self.assertRaisesRegex(IsaacRunnerError, "Model runtime is unavailable"):
                    run_isaac_job(
                        self.manifest_path,
                        self.root / f"digest-{mismatch}",
                        app_factory=lambda: app_factory_calls.append(True),
                        model_entrypoint_loader=lambda _entrypoint: (
                            lambda _artifact: lambda _payload: self.model_output(_payload)
                        ),
                    )
                self.assertEqual(app_factory_calls, [])

    def test_model_input_is_required_for_configured_model(self) -> None:
        manifest = self.make_manifest()
        self.add_model_config(manifest)
        self.write_manifest(manifest)
        app = FakeSimulationApp()

        bundle_path = run_isaac_job(
            self.manifest_path,
            self.root / "missing-model-input",
            app_factory=lambda: app,
            version_reader=lambda: "1.2.3",
            adapter_factory=lambda *args: FakeIsaacAdapter(*args),
            model_entrypoint_loader=lambda _entrypoint: (
                lambda _artifact: lambda _payload: self.model_output(_payload)
            ),
        )
        _bundle_manifest, inspection_run, _artifacts = read_result_bundle(bundle_path)

        self.assertEqual(inspection_run["status"], "COMPLETED_WITH_ERRORS")
        self.assertTrue(all(item["observation"] is None for item in inspection_run["results"]))
        self.assertTrue(all("model_input" in item["error"] for item in inspection_run["results"]))

    def test_model_inference_failure_does_not_fall_back_to_rules(self) -> None:
        manifest = self.make_manifest()
        self.add_model_config(manifest)
        self.write_manifest(manifest)
        app = FakeSimulationApp()

        def loader(_entrypoint):
            def build(_artifact):
                def predict(_payload):
                    raise RuntimeError("weights unavailable")

                return predict

            return build

        bundle_path = run_isaac_job(
            self.manifest_path,
            self.root / "model-failure",
            app_factory=lambda: app,
            version_reader=lambda: "1.2.3",
            adapter_factory=lambda *args: ModelInputIsaacAdapter(*args),
            model_entrypoint_loader=loader,
        )
        _bundle_manifest, inspection_run, _artifacts = read_result_bundle(bundle_path)

        self.assertEqual(inspection_run["status"], "COMPLETED_WITH_ERRORS")
        self.assertTrue(all(item["observation"] is None for item in inspection_run["results"]))
        self.assertTrue(all("no fallback" in item["error"] for item in inspection_run["results"]))

    def test_adapter_cannot_relabel_synthetic_data_as_isaac(self) -> None:
        app = FakeSimulationApp()
        adapter_holder: list[FakeIsaacAdapter] = []

        def create_adapter(*args):
            adapter = FakeIsaacAdapter(*args, observation_source="synthetic_simulation")
            adapter_holder.append(adapter)
            return adapter

        with self.assertLogs("inspection_system.platform.isaac_runner", level="ERROR") as captured:
            bundle_path = run_isaac_job(
                self.manifest_path,
                self.root / "output",
                app_factory=lambda: app,
                version_reader=lambda: "1.2.3",
                adapter_factory=create_adapter,
            )
        bundle_manifest, inspection_run, _artifacts = read_result_bundle(bundle_path)
        self.assertEqual(bundle_manifest["source"], "isaac_sim")
        self.assertEqual(inspection_run["status"], "COMPLETED_WITH_ERRORS")
        self.assertTrue(all(item["observation"] is None for item in inspection_run["results"]))
        self.assertTrue(adapter_holder[0].closed)
        payload = json.loads(JsonLogFormatter().format(captured.records[0]))
        self.assertEqual(payload["run_id"], "RUN-0000000000000001")
        self.assertEqual(payload["waypoint_id"], self.config["waypoints"][0]["waypoint_id"])
        self.assertEqual(payload["execution_backend"], "isaac_sim")
        self.assertEqual(payload["error_type"], "IsaacRunnerError")

    def test_isaac_slurm_requires_explicit_runtime_and_resource_configuration(self) -> None:
        identity = self.root / "id_ed25519"
        known_hosts = self.root / "known_hosts"
        identity.write_text("test-only", encoding="utf-8")
        known_hosts.write_text("test-only", encoding="utf-8")
        settings = Settings(
            database_url="sqlite:///:memory:",
            environment="test",
            executor_mode="slurm",
            auth_mode="development",
            slurm_host="cluster.example.test",
            slurm_user="inspection-user",
            slurm_identity_file=identity,
            slurm_known_hosts_file=known_hosts,
            slurm_remote_root="/home/inspection/runs",
            slurm_source="isaac_sim",
        )
        with self.assertRaisesRegex(ValueError, "Isaac Sim Slurm execution requires"):
            settings.validate()

        settings = Settings(
            **{
                **settings.__dict__,
                "isaac_sim_version": "1.2.3",
                "isaac_robot_usd_path": str(self.asset),
                "isaac_sim_python": str(self.python),
                "isaac_sim_adapter": "inspection_system.adapters.site:build",
                "isaac_slurm_gres": "gpu:1",
            }
        )
        settings.validate()

    def test_slurm_submit_bundles_isaac_runner_and_requests_configured_gpu(self) -> None:
        identity = self.root / "id_ed25519"
        known_hosts = self.root / "known_hosts"
        identity.write_text("test-only", encoding="utf-8")
        known_hosts.write_text("test-only", encoding="utf-8")
        settings = Settings(
            database_url="sqlite:///:memory:",
            environment="test",
            executor_mode="slurm",
            auth_mode="development",
            slurm_host="cluster.example.test",
            slurm_user="inspection-user",
            slurm_identity_file=identity,
            slurm_known_hosts_file=known_hosts,
            slurm_remote_root="/home/inspection/runs",
            slurm_source="isaac_sim",
            isaac_sim_version="1.2.3",
            isaac_robot_usd_path=str(self.asset),
            isaac_sim_python=str(self.python),
            isaac_sim_adapter="inspection_system.adapters.site:build",
            isaac_slurm_gres="gpu:1",
        )
        client = object.__new__(SlurmClient)
        client.settings = settings
        client.target = "inspection-user@cluster.example.test"
        client.remote_root = settings.slurm_remote_root
        remote_commands: list[str] = []
        bundled_files: set[str] = set()
        uploaded_manifest_digests: list[str] = []

        def fake_run(argv, **_kwargs):
            if argv[0] == "scp":
                with tarfile.open(argv[-3], "r:gz") as archive:
                    bundled_files.update(archive.getnames())
                uploaded_manifest_digests.append(
                    hashlib.sha256(Path(argv[-2]).read_bytes()).hexdigest())
            return ""

        def fake_remote(command: str) -> str:
            remote_commands.append(command)
            return "420" if "sbatch" in command else ""

        client._run = fake_run
        client._remote = fake_remote
        manifest = {
            "run_id": "RUN-0000000000000001",
            "source": "isaac_sim",
            "simulator": {
                "expected_version": settings.isaac_sim_version,
                "robot_usd_path": settings.isaac_robot_usd_path,
                "python_path": settings.isaac_sim_python,
                "adapter_entrypoint": settings.isaac_sim_adapter,
            },
        }
        job_id, remote_dir = client.submit(manifest)

        self.assertEqual(job_id, "420")
        self.assertEqual(remote_dir, "/home/inspection/runs/RUN-0000000000000001")
        self.assertIn("src/inspection_system/platform/isaac_runner.py", bundled_files)
        self.assertIn("scripts/slurm/run_inspection.sh", bundled_files)
        self.assertIn("--gres=gpu:1", remote_commands[-1])
        self.assertIn("--cpus-per-task=4", remote_commands[-1])
        self.assertIn("--mem=16G", remote_commands[-1])
        self.assertIn("--time=02:00:00", remote_commands[-1])
        self.assertIn(
            f"INSPECTION_MANIFEST_SHA256={uploaded_manifest_digests[0]}",
            remote_commands[-1],
        )


if __name__ == "__main__":
    unittest.main()
