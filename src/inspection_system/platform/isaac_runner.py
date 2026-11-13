from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import importlib
import json
import logging
import math
import os
from pathlib import Path, PurePosixPath
import re
import tempfile
from typing import Any, Callable, Protocol

from ..config import load_site_config, waypoints_from_config
from ..models import (
    Assessment,
    InspectionRun,
    Observation,
    Severity,
    Waypoint,
    WaypointResult,
)
from ..perception.model_runtime import ModelRuntime, ModelRuntimeError
from ..perception.rules import RuleBasedDiagnosticEngine
from .logging_config import configure_logging
from .result_bundle import build_result_bundle

logger = logging.getLogger(__name__)
_RUN_ID = re.compile(r"^RUN-[0-9A-F]{16}$")
_VERSION = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+(?:[-+][0-9A-Za-z.-]+)?$")
_ARTIFACT_NAME = re.compile(r"^[A-Za-z0-9._-]{1,255}$")
_MEDIA_TYPE = re.compile(r"^[A-Za-z0-9!#$&^_.+-]+/[A-Za-z0-9!#$&^_.+-]+$")
_ENTRYPOINT = re.compile(
    r"^[A-Za-z_][A-Za-z0-9_.]*(?::[A-Za-z_][A-Za-z0-9_]*)+$"
)
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_MODEL_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_MODEL_CONFIG_KEYS = {
    "manifest_path", "manifest_sha256", "artifact_sha256", "model_id", "model_version",
}


class IsaacRunnerError(RuntimeError):
    """The configured Isaac Sim execution environment is not usable."""


@dataclass(frozen=True)
class IsaacMission:
    manifest: dict[str, Any]
    waypoints: tuple[Waypoint, ...]
    expected_version: str
    robot_usd_path: Path
    python_path: Path
    adapter_entrypoint: str
    model_config: dict[str, Any] | None
    manifest_sha256: str


@dataclass(frozen=True)
class WaypointArtifact:
    name: str
    sensor_id: str
    media_type: str
    timestamp_utc: str
    path: Path


@dataclass(frozen=True)
class WaypointCapture:
    navigation_status: str
    inspection_status: str
    observation: Observation | None
    error: str | None = None
    artifacts: tuple[WaypointArtifact, ...] = ()


class IsaacExecutionAdapter(Protocol):
    def start(self) -> None: ...

    def inspect_waypoint(
        self, waypoint: Waypoint, *, seed: int, index: int
    ) -> WaypointCapture: ...

    def close(self) -> None: ...


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _remote_file_path(value: Any, field: str) -> Path:
    if not isinstance(value, str) or not value.startswith("/"):
        raise IsaacRunnerError(f"Manifest simulator.{field} must be an absolute path.")
    path = PurePosixPath(value)
    if ".." in path.parts:
        raise IsaacRunnerError(f"Manifest simulator.{field} cannot contain '..'.")
    return Path(value)


def load_isaac_manifest(path: Path) -> IsaacMission:
    try:
        raw_bytes = path.read_bytes()
        manifest = json.loads(raw_bytes)
    except FileNotFoundError as exc:
        raise IsaacRunnerError("Mission manifest does not exist.") from exc
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise IsaacRunnerError("Mission manifest is unreadable or invalid JSON.") from exc

    if not isinstance(manifest, dict) or manifest.get("schema_version") != 1:
        raise IsaacRunnerError("Unsupported mission manifest schema.")
    if manifest.get("source") != "isaac_sim":
        raise IsaacRunnerError("Isaac runner accepts only source='isaac_sim'.")
    if not isinstance(manifest.get("run_id"), str) or not _RUN_ID.fullmatch(manifest["run_id"]):
        raise IsaacRunnerError("Manifest run_id is invalid.")
    seed = manifest.get("seed")
    if isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed <= 2**31 - 1:
        raise IsaacRunnerError("Manifest seed must be a non-negative 32-bit integer.")

    site_config = manifest.get("site_config")
    if not isinstance(site_config, dict):
        raise IsaacRunnerError("Manifest is missing its frozen site_config.")
    try:
        with tempfile.TemporaryDirectory(prefix="isaac-manifest-") as temp_dir:
            config_path = Path(temp_dir) / "site.json"
            config_path.write_text(
                json.dumps(site_config, ensure_ascii=False), encoding="utf-8"
            )
            validated_config = load_site_config(config_path)
    except (OSError, ValueError) as exc:
        raise IsaacRunnerError(f"Frozen site configuration is invalid: {exc}") from exc

    if manifest.get("site_id") != validated_config["site_id"]:
        raise IsaacRunnerError("Manifest site_id does not match frozen site_config.")
    if manifest.get("robot_id") != validated_config["robot"]["robot_id"]:
        raise IsaacRunnerError("Manifest robot_id does not match frozen site_config.")
    expected_waypoints = [item.waypoint_id for item in waypoints_from_config(validated_config)]
    if manifest.get("waypoint_ids") != expected_waypoints:
        raise IsaacRunnerError("Manifest waypoint order does not match frozen site_config.")

    config_digest = hashlib.sha256(_canonical_json(validated_config)).hexdigest()
    if manifest.get("config_sha256") != config_digest:
        raise IsaacRunnerError("Frozen site_config checksum does not match config_sha256.")

    simulator = manifest.get("simulator")
    if not isinstance(simulator, dict):
        raise IsaacRunnerError("Manifest is missing the administrator Isaac Sim configuration.")
    expected_version = simulator.get("expected_version")
    if not isinstance(expected_version, str) or not _VERSION.fullmatch(expected_version):
        raise IsaacRunnerError("Manifest simulator.expected_version is invalid or unset.")
    asset_path = _remote_file_path(simulator.get("robot_usd_path"), "robot_usd_path")
    if not asset_path.is_file():
        raise IsaacRunnerError(f"Configured robot USD asset is unavailable: {asset_path}")
    python_path = _remote_file_path(simulator.get("python_path"), "python_path")
    if not python_path.is_file() or not os.access(python_path, os.X_OK):
        raise IsaacRunnerError(
            f"Configured Isaac Sim Python launcher is unavailable: {python_path}"
        )
    adapter_entrypoint = simulator.get("adapter_entrypoint")
    if not isinstance(adapter_entrypoint, str) or not _ENTRYPOINT.fullmatch(adapter_entrypoint):
        raise IsaacRunnerError("Manifest simulator.adapter_entrypoint is invalid or unset.")
    model_config = simulator.get("model")
    if model_config is not None:
        if not isinstance(model_config, dict) or set(model_config) != _MODEL_CONFIG_KEYS:
            raise IsaacRunnerError("Manifest simulator.model does not match the model contract.")
        model_manifest_path = _remote_file_path(
            model_config.get("manifest_path"), "model.manifest_path")
        if not model_manifest_path.is_file():
            raise IsaacRunnerError(
                f"Configured model manifest is unavailable: {model_manifest_path}"
            )
        if (not isinstance(model_config.get("manifest_sha256"), str)
                or not _SHA256.fullmatch(model_config["manifest_sha256"])
                or not isinstance(model_config.get("artifact_sha256"), str)
                or not _SHA256.fullmatch(model_config["artifact_sha256"])):
            raise IsaacRunnerError("Manifest simulator.model SHA-256 values are invalid.")
        if (not isinstance(model_config.get("model_id"), str)
                or not _MODEL_ID.fullmatch(model_config["model_id"])
                or not isinstance(model_config.get("model_version"), str)
                or not _VERSION.fullmatch(model_config["model_version"])):
            raise IsaacRunnerError("Manifest simulator.model identity is invalid.")
    return IsaacMission(
        manifest=manifest,
        waypoints=tuple(waypoints_from_config(validated_config)),
        expected_version=expected_version,
        robot_usd_path=asset_path,
        python_path=python_path,
        adapter_entrypoint=adapter_entrypoint,
        model_config=model_config,
        manifest_sha256=hashlib.sha256(raw_bytes).hexdigest(),
    )


def _create_simulation_app() -> Any:
    try:
        from isaacsim.simulation_app import SimulationApp
    except ImportError as exc:
        raise IsaacRunnerError(
            "Isaac Sim runtime is unavailable. Run with the configured Isaac Sim Python launcher."
        ) from exc
    return SimulationApp({"headless": True})


def _read_runtime_version() -> str:
    try:
        from isaacsim.core.version import get_version
    except ImportError as exc:
        raise IsaacRunnerError("Isaac Sim version extension is unavailable.") from exc
    version = get_version()[0]
    if not isinstance(version, str) or not version:
        raise IsaacRunnerError("Isaac Sim did not report a valid runtime version.")
    return version


def _load_adapter_factory(entrypoint: str) -> Callable[..., IsaacExecutionAdapter]:
    module_name, function_name = entrypoint.split(":", 1)
    try:
        factory = getattr(importlib.import_module(module_name), function_name)
    except (ImportError, AttributeError) as exc:
        raise IsaacRunnerError(
            f"Configured Isaac adapter cannot be loaded: {entrypoint}."
        ) from exc
    if not callable(factory):
        raise IsaacRunnerError("Configured Isaac adapter factory is not callable.")
    return factory


def _validate_observation(
    observation: Observation, mission: IsaacMission, waypoint: Waypoint
) -> None:
    if observation.source != "isaac_sim":
        raise IsaacRunnerError("Observation source must be exactly 'isaac_sim'.")
    if observation.robot_id != mission.manifest["robot_id"]:
        raise IsaacRunnerError("Observation robot_id does not match the mission.")
    if observation.waypoint_id != waypoint.waypoint_id:
        raise IsaacRunnerError("Observation waypoint_id does not match the requested waypoint.")
    if observation.device_id != waypoint.device_id:
        raise IsaacRunnerError("Observation device_id does not match the frozen waypoint.")
    if not isinstance(observation.timestamp_utc, str):
        raise IsaacRunnerError("Observation timestamp_utc must be an ISO-8601 string.")
    try:
        timestamp = datetime.fromisoformat(observation.timestamp_utc.replace("Z", "+00:00"))
    except ValueError as exc:
        raise IsaacRunnerError("Observation timestamp_utc is invalid.") from exc
    if timestamp.tzinfo is None or timestamp.utcoffset() != timezone.utc.utcoffset(timestamp):
        raise IsaacRunnerError("Observation timestamp_utc must be normalized to UTC.")

    for name in ("pressure_mpa", "temperature_c", "ambient_temperature_c"):
        value = getattr(observation, name)
        if value is not None and (
            isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value)
        ):
            raise IsaacRunnerError(f"Observation {name} must be a finite number or null.")
    for name in ("cabinet_door_closed", "leak_detected"):
        value = getattr(observation, name)
        if value is not None and not isinstance(value, bool):
            raise IsaacRunnerError(f"Observation {name} must be boolean or null.")
    for name in ("model_version", "calibration_version"):
        value = getattr(observation, name)
        if value is not None and (not isinstance(value, str) or not value.strip()
                                  or len(value) > 128):
            raise IsaacRunnerError(f"Observation {name} must be a non-empty string or null.")
    if (not isinstance(observation.quality_flags, list)
            or len(observation.quality_flags) > 64
            or any(not isinstance(flag, str) or not flag.strip() or len(flag) > 128
                   for flag in observation.quality_flags)
            or len(set(observation.quality_flags)) != len(observation.quality_flags)):
        raise IsaacRunnerError(
            "Observation quality_flags must be a list of unique non-empty strings."
        )
    if (observation.inference_latency_ms is not None
            and (isinstance(observation.inference_latency_ms, bool)
                 or not isinstance(observation.inference_latency_ms, (int, float))
                 or not math.isfinite(observation.inference_latency_ms)
                 or observation.inference_latency_ms < 0)):
        raise IsaacRunnerError(
            "Observation inference_latency_ms must be a finite non-negative number or null."
        )
    if not isinstance(observation.sensor_confidence, dict):
        raise IsaacRunnerError("Observation sensor_confidence must be an object.")
    for key, value in observation.sensor_confidence.items():
        if (
            not isinstance(key, str)
            or isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or not 0 <= value <= 1
        ):
            raise IsaacRunnerError("Sensor confidence values must be finite numbers in [0, 1].")
    if not isinstance(observation.domain, dict):
        raise IsaacRunnerError("Observation domain metadata must be an object.")
    sensor_provenance = observation.domain.get("sensor_provenance")
    if (
        not isinstance(sensor_provenance, dict)
        or not isinstance(sensor_provenance.get("sensor_ids"), list)
        or not sensor_provenance["sensor_ids"]
        or any(not isinstance(item, str) or not item for item in sensor_provenance["sensor_ids"])
        or not isinstance(sensor_provenance.get("frame_id"), str)
        or not sensor_provenance["frame_id"]
    ):
        raise IsaacRunnerError(
            "Observation must identify at least one sensor stream and its frame_id."
        )
    if (
        observation.temperature_c is not None
        and observation.domain.get("temperature_semantics") != "simulated_proxy"
    ):
        raise IsaacRunnerError(
            "Isaac Sim temperature values must be explicitly marked simulated_proxy."
        )
    try:
        json.dumps(observation.domain, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise IsaacRunnerError("Observation domain metadata must be finite JSON data.") from exc


def _capture_result(
    capture: WaypointCapture,
    mission: IsaacMission,
    waypoint: Waypoint,
    index: int,
    runtime_version: str,
    engine: RuleBasedDiagnosticEngine,
    model_runtime: ModelRuntime | None = None,
) -> WaypointResult:
    allowed_navigation = {"SUCCEEDED", "FAILED", "SKIPPED"}
    allowed_inspection = {"COMPLETED", "FAILED", "SKIPPED"}
    if not isinstance(capture, WaypointCapture):
        raise IsaacRunnerError("Isaac adapter returned an invalid WaypointCapture.")
    if capture.navigation_status not in allowed_navigation:
        raise IsaacRunnerError("Isaac adapter returned an unsupported navigation status.")
    if capture.inspection_status not in allowed_inspection:
        raise IsaacRunnerError("Isaac adapter returned an unsupported inspection status.")
    if capture.navigation_status == "FAILED" and (
        capture.inspection_status != "SKIPPED" or capture.observation is not None
    ):
        raise IsaacRunnerError("A failed navigation cannot claim an inspection observation.")
    if capture.inspection_status == "COMPLETED" and capture.observation is None:
        raise IsaacRunnerError("Completed inspection must contain an observation.")

    observation = capture.observation
    assessment: Assessment | None = None
    order = None
    if observation is not None:
        if model_runtime is not None:
            model_input = observation.domain.get("model_input") \
                if isinstance(observation.domain, dict) else None
            if not isinstance(model_input, dict):
                raise IsaacRunnerError(
                    "Configured model inference requires observation.domain.model_input."
                )
            expected_sample_id = (
                f"{mission.manifest['run_id']}-{index:03d}-{waypoint.waypoint_id}"
            )
            normalized_input = {
                **model_input,
                "sample_id": expected_sample_id,
                "timestamp_utc": observation.timestamp_utc,
                "waypoint_id": waypoint.waypoint_id,
                "device_id": waypoint.device_id,
                "sensor_provenance": observation.domain.get("sensor_provenance"),
            }
            try:
                model_output = model_runtime.infer(normalized_input)
            except ModelRuntimeError as exc:
                raise IsaacRunnerError(str(exc)) from exc
            for field in (
                "pressure_mpa", "temperature_c", "ambient_temperature_c",
                "cabinet_door_closed", "leak_detected", "sensor_confidence",
                "model_version", "calibration_version", "quality_flags",
                "inference_latency_ms",
            ):
                setattr(observation, field, model_output[field])
            observation.domain = {
                key: value for key, value in observation.domain.items()
                if key != "model_input"
            }
            observation.domain["model_provenance"] = {
                "model_id": model_runtime.manifest.model_id,
                "model_version": model_runtime.manifest.model_version,
                "manifest_sha256": model_runtime.manifest.manifest_sha256,
                "artifact_sha256": model_runtime.manifest.artifact.sha256,
                "input_schema": model_runtime.manifest.input_schema,
                "output_schema": model_runtime.manifest.output_schema,
            }
        _validate_observation(observation, mission, waypoint)
        observation.sample_id = (
            f"{mission.manifest['run_id']}-{index:03d}-{waypoint.waypoint_id}"
        )
        observation.domain = {
            **observation.domain,
            "simulation_provenance": {
                "runtime": "Isaac Sim",
                "runtime_version": runtime_version,
                "seed": mission.manifest["seed"],
                "manifest_sha256": mission.manifest_sha256,
                "robot_usd_path": str(mission.robot_usd_path),
            },
        }
        assessment = engine.assess(observation, waypoint)
        order = engine.create_work_order(
            observation,
            waypoint,
            assessment,
            mission.manifest["site_id"],
            run_id=mission.manifest["run_id"],
        )

    return WaypointResult(
        waypoint_id=waypoint.waypoint_id,
        device_id=waypoint.device_id,
        navigation_status=capture.navigation_status,
        inspection_status=capture.inspection_status,
        observation=observation,
        assessment=assessment,
        work_order=order,
        error=(capture.error[:1000] if capture.error else None),
    )


def _prepare_capture_artifacts(
    capture: WaypointCapture,
    waypoint: Waypoint,
    existing_names: set[str],
) -> tuple[list[dict[str, str]], dict[str, Path]]:
    if not isinstance(capture.artifacts, tuple):
        raise IsaacRunnerError("Waypoint artifacts must be an immutable tuple.")
    if not capture.artifacts:
        return [], {}
    if (capture.navigation_status != "SUCCEEDED"
            or capture.inspection_status != "COMPLETED"
            or capture.observation is None):
        raise IsaacRunnerError("Sensor artifacts require a completed waypoint observation.")

    provenance = capture.observation.domain.get("sensor_provenance")
    if not isinstance(provenance, dict) or not isinstance(provenance.get("sensor_ids"), list):
        raise IsaacRunnerError("Sensor artifacts require sensor provenance in the observation.")
    sensor_ids = provenance["sensor_ids"]
    refs: list[dict[str, str]] = []
    files: dict[str, Path] = {}
    for artifact in capture.artifacts:
        if not isinstance(artifact, WaypointArtifact):
            raise IsaacRunnerError("Isaac adapter returned an invalid waypoint artifact.")
        if (not _ARTIFACT_NAME.fullmatch(artifact.name)
                or artifact.name in {".", "..", "result_manifest.json"}):
            raise IsaacRunnerError("Waypoint artifact name is invalid.")
        if (not isinstance(artifact.sensor_id, str)
                or artifact.sensor_id not in sensor_ids):
            raise IsaacRunnerError("Waypoint artifact references an unknown sensor stream.")
        if (not isinstance(artifact.media_type, str) or len(artifact.media_type) > 127
                or not _MEDIA_TYPE.fullmatch(artifact.media_type)):
            raise IsaacRunnerError("Waypoint artifact media type is invalid.")
        if not isinstance(artifact.timestamp_utc, str):
            raise IsaacRunnerError("Waypoint artifact timestamp must be UTC.")
        try:
            captured_at = datetime.fromisoformat(
                artifact.timestamp_utc[:-1] + "+00:00"
                if artifact.timestamp_utc.endswith("Z") else artifact.timestamp_utc)
        except ValueError as exc:
            raise IsaacRunnerError("Waypoint artifact timestamp is invalid.") from exc
        if captured_at.tzinfo is None or captured_at.utcoffset() != timezone.utc.utcoffset(captured_at):
            raise IsaacRunnerError("Waypoint artifact timestamp must be normalized to UTC.")
        timestamp = captured_at.astimezone(timezone.utc).isoformat(timespec="seconds")
        name = f"{waypoint.waypoint_id}__{artifact.name}"
        path = Path(artifact.path)
        if (not _ARTIFACT_NAME.fullmatch(name)
                or name in existing_names or name in files
                or path.is_symlink() or not path.is_file() or path.stat().st_size == 0):
            raise IsaacRunnerError("Waypoint artifact path, name, or size is invalid.")
        files[name] = path
        refs.append({
            "name": name,
            "sensor_id": artifact.sensor_id,
            "media_type": artifact.media_type,
            "timestamp_utc": timestamp,
        })
    return refs, files


def run_isaac_job(
    manifest_path: Path,
    output_dir: Path,
    *,
    app_factory: Callable[[], Any] | None = None,
    version_reader: Callable[[], str] | None = None,
    adapter_factory: Callable[..., IsaacExecutionAdapter] | None = None,
    model_entrypoint_loader: Callable[..., Any] | None = None,
) -> Path:
    mission = load_isaac_manifest(manifest_path)
    model_runtime: ModelRuntime | None = None
    if mission.model_config is not None:
        try:
            model_runtime = ModelRuntime.load(
                Path(mission.model_config["manifest_path"]),
                expected_manifest_sha256=mission.model_config["manifest_sha256"],
                expected_artifact_sha256=mission.model_config["artifact_sha256"],
                expected_model_id=mission.model_config["model_id"],
                expected_model_version=mission.model_config["model_version"],
                entrypoint_loader=model_entrypoint_loader,
            )
        except ModelRuntimeError as exc:
            raise IsaacRunnerError(f"Model runtime is unavailable: {exc}") from exc
    app = (app_factory or _create_simulation_app)()
    adapter: IsaacExecutionAdapter | None = None
    log_context = {
        "run_id": mission.manifest["run_id"],
        "execution_backend": "isaac_sim",
    }
    try:
        runtime_version = (version_reader or _read_runtime_version)()
        if runtime_version != mission.expected_version:
            raise IsaacRunnerError(
                f"Isaac Sim version mismatch: expected {mission.expected_version}, "
                f"found {runtime_version}."
            )
        factory = adapter_factory or _load_adapter_factory(mission.adapter_entrypoint)
        adapter = factory(app, mission.manifest, mission.waypoints)
        for method in ("start", "inspect_waypoint", "close"):
            if not callable(getattr(adapter, method, None)):
                raise IsaacRunnerError(f"Isaac adapter does not implement {method}().")
        adapter.start()
        app.update()
        logger.info("Isaac mission execution started", extra=log_context)

        engine = RuleBasedDiagnosticEngine()
        started = datetime.now(timezone.utc).isoformat(timespec="seconds")
        results: list[WaypointResult] = []
        artifact_files: dict[str, Path] = {}
        for index, waypoint in enumerate(mission.waypoints, start=1):
            try:
                capture = adapter.inspect_waypoint(
                    waypoint, seed=mission.manifest["seed"], index=index
                )
                result = _capture_result(
                    capture, mission, waypoint, index, runtime_version, engine,
                    model_runtime,
                )
                artifact_refs, files = _prepare_capture_artifacts(
                    capture, waypoint, set(artifact_files))
                if artifact_refs:
                    sensor_provenance = result.observation.domain["sensor_provenance"]
                    sensor_provenance["artifacts"] = artifact_refs
                artifact_files.update(files)
                results.append(result)
            except Exception as exc:
                if isinstance(exc, IsaacRunnerError):
                    logger.error(
                        "Isaac waypoint output rejected: %s",
                        exc,
                        extra={**log_context, "waypoint_id": waypoint.waypoint_id,
                               "error_type": type(exc).__name__},
                    )
                else:
                    logger.exception(
                        "Isaac waypoint execution failed",
                        extra={**log_context, "waypoint_id": waypoint.waypoint_id,
                               "error_type": type(exc).__name__},
                    )
                results.append(WaypointResult(
                    waypoint_id=waypoint.waypoint_id,
                    device_id=waypoint.device_id,
                    navigation_status="FAILED",
                    inspection_status="FAILED",
                    observation=None,
                    assessment=None,
                    work_order=None,
                    error=f"{type(exc).__name__}: {exc}"[:1000],
                ))
            app.update()

        status = "COMPLETED" if all(
            item.navigation_status == "SUCCEEDED"
            and item.inspection_status == "COMPLETED"
            and item.observation is not None
            for item in results
        ) else "COMPLETED_WITH_ERRORS"
        run = InspectionRun(
            run_id=mission.manifest["run_id"],
            site_id=mission.manifest["site_id"],
            robot_id=mission.manifest["robot_id"],
            started_at_utc=started,
            finished_at_utc=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            status=status,
            results=results,
            source="isaac_sim",
        )
        bundle_path = build_result_bundle(
            output_dir,
            run,
            mission.manifest["config_sha256"],
            software_version=f"isaac-sim/{runtime_version}",
            additional_artifacts=artifact_files,
        )
        logger.info(
            "Isaac mission execution finished",
            extra={**log_context, "result_status": status},
        )
        return bundle_path
    finally:
        if adapter is not None:
            try:
                adapter.close()
            except Exception:
                logger.exception("Isaac adapter cleanup failed.")
        app.close()


def main() -> int:
    project_root = Path(__file__).resolve().parents[3]
    configure_logging(project_root / "configs" / "logging.json")
    parser = argparse.ArgumentParser(
        description="Run a frozen mission with the configured Isaac Sim adapter."
    )
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = run_isaac_job(args.manifest, args.output_dir)
    except (IsaacRunnerError, OSError, ValueError) as exc:
        parser.exit(2, f"isaac_runner: {exc}\n")
    print(f"result_bundle={result}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
