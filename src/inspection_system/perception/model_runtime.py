from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import importlib
import json
import math
from pathlib import Path
import platform
import re
from typing import Any, Callable, Mapping, Protocol


MODEL_MANIFEST_SCHEMA_VERSION = 1
MODEL_INPUT_SCHEMA_VERSION = "inspection-model-input/v1"
MODEL_OUTPUT_SCHEMA_VERSION = "inspection-model-output/v1"
_MODEL_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_VERSION = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+(?:[-+][0-9A-Za-z.-]+)?$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_ENTRYPOINT = re.compile(
    r"^[A-Za-z_][A-Za-z0-9_.]*(?::[A-Za-z_][A-Za-z0-9_]*)+$"
)
_CHUNK_SIZE = 1024 * 1024

_MANIFEST_KEYS = {
    "schema_version",
    "model_id",
    "model_version",
    "task",
    "runtime",
    "input_schema",
    "output_schema",
    "artifact",
}
_RUNTIME_KEYS = {"name", "version", "entrypoint"}
_ARTIFACT_KEYS = {"path", "sha256", "size_bytes"}
_INPUT_KEYS = {
    "schema_version",
    "sample_id",
    "timestamp_utc",
    "waypoint_id",
    "device_id",
    "sensor_provenance",
    "features",
}
_SENSOR_PROVENANCE_KEYS = {"sensor_ids", "frame_id"}
_OUTPUT_KEYS = {
    "schema_version",
    "sample_id",
    "model_version",
    "calibration_version",
    "pressure_mpa",
    "temperature_c",
    "ambient_temperature_c",
    "cabinet_door_closed",
    "leak_detected",
    "sensor_confidence",
    "quality_flags",
    "inference_latency_ms",
}


class ModelRuntimeError(RuntimeError):
    """The configured model contract cannot be safely executed."""


@dataclass(frozen=True)
class ModelArtifact:
    path: Path
    sha256: str
    size_bytes: int


@dataclass(frozen=True)
class ModelManifest:
    model_id: str
    model_version: str
    task: str
    runtime_name: str
    runtime_version: str
    entrypoint: str
    input_schema: str
    output_schema: str
    artifact: ModelArtifact
    manifest_sha256: str


class ModelPredictor(Protocol):
    def __call__(self, payload: Mapping[str, Any]) -> Mapping[str, Any]: ...


def _object(value: Any, label: str, expected_keys: set[str]) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ModelRuntimeError(f"{label} must be an object.")
    missing = expected_keys - value.keys()
    extra = value.keys() - expected_keys
    if missing or extra:
        raise ModelRuntimeError(
            f"{label} fields do not match the model contract "
            f"(missing={sorted(missing)}, extra={sorted(extra)})."
        )
    return value


def _text(value: Any, label: str, *, limit: int = 1024) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ModelRuntimeError(
            f"{label} must be a non-empty string of at most {limit} characters."
        )
    return value


def _finite_json(value: Any, label: str) -> None:
    try:
        json.dumps(value, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ModelRuntimeError(f"{label} must contain finite JSON values only.") from exc


def _finite_number(value: Any, label: str) -> None:
    if value is None:
        return
    try:
        valid = (
            not isinstance(value, bool)
            and isinstance(value, (int, float))
            and math.isfinite(float(value))
        )
    except (OverflowError, TypeError, ValueError):
        valid = False
    if not valid:
        raise ModelRuntimeError(f"{label} must be a finite number or null.")


def _utc_datetime(value: Any, label: str) -> datetime:
    if not isinstance(value, str):
        raise ModelRuntimeError(f"{label} must be an ISO-8601 UTC timestamp.")
    try:
        parsed = datetime.fromisoformat(
            value[:-1] + "+00:00" if value.endswith("Z") else value
        )
    except ValueError as exc:
        raise ModelRuntimeError(f"{label} is not a valid ISO-8601 timestamp.") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise ModelRuntimeError(f"{label} must be normalized to UTC.")
    return parsed.astimezone(timezone.utc)


def _artifact_path(manifest_path: Path, value: Any) -> Path:
    path_text = _text(value, "artifact.path", limit=4096)
    path = Path(path_text).expanduser()
    if path.is_symlink():
        raise ModelRuntimeError("Model artifact path must not be a symbolic link.")
    if not path.is_absolute():
        root = manifest_path.parent.resolve()
        candidate = root / path
        if candidate.is_symlink():
            raise ModelRuntimeError("Model artifact path must not be a symbolic link.")
        path = candidate.resolve()
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise ModelRuntimeError(
                "artifact.path must stay inside the model manifest directory when relative."
            ) from exc
    return path


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            while chunk := stream.read(_CHUNK_SIZE):
                digest.update(chunk)
    except OSError as exc:
        raise ModelRuntimeError(f"Model artifact cannot be read: {path}") from exc
    return digest.hexdigest()


def _validate_artifact(manifest_path: Path, raw: Any) -> ModelArtifact:
    artifact = _object(raw, "artifact", _ARTIFACT_KEYS)
    path = _artifact_path(manifest_path, artifact["path"])
    digest = artifact["sha256"]
    size = artifact["size_bytes"]
    if not isinstance(digest, str) or not _SHA256.fullmatch(digest):
        raise ModelRuntimeError("artifact.sha256 must be a lowercase SHA-256 digest.")
    if type(size) is not int or size <= 0:
        raise ModelRuntimeError("artifact.size_bytes must be a positive integer.")
    if path.is_symlink() or not path.is_file():
        raise ModelRuntimeError(f"Model artifact is unavailable: {path}")
    try:
        actual_size = path.stat().st_size
    except OSError as exc:
        raise ModelRuntimeError(f"Model artifact metadata cannot be read: {path}") from exc
    if actual_size != size:
        raise ModelRuntimeError(
            f"Model artifact size mismatch: expected {size}, found {actual_size}."
        )
    actual_digest = _sha256_file(path)
    if actual_digest != digest:
        raise ModelRuntimeError("Model artifact SHA-256 does not match the manifest.")
    return ModelArtifact(path=path, sha256=digest, size_bytes=size)


def load_model_manifest(
    path: Path,
    *,
    runtime_version: str | None = None,
    expected_manifest_sha256: str | None = None,
    expected_artifact_sha256: str | None = None,
    expected_model_id: str | None = None,
    expected_model_version: str | None = None,
) -> ModelManifest:
    """Validate a versioned manifest and its content-addressed artifact."""
    manifest_path = Path(path).expanduser().resolve()
    try:
        raw_bytes = manifest_path.read_bytes()
        raw = json.loads(raw_bytes, parse_constant=lambda value: (_ for _ in ()).throw(
            ValueError(f"non-standard JSON number: {value}")
        ))
    except FileNotFoundError as exc:
        raise ModelRuntimeError(f"Model manifest does not exist: {manifest_path}") from exc
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise ModelRuntimeError("Model manifest is unreadable or invalid JSON.") from exc

    manifest_sha256 = hashlib.sha256(raw_bytes).hexdigest()
    if expected_manifest_sha256 is not None and manifest_sha256 != expected_manifest_sha256:
        raise ModelRuntimeError("Model manifest SHA-256 does not match the frozen mission.")

    manifest = _object(raw, "model manifest", _MANIFEST_KEYS)
    if type(manifest["schema_version"]) is not int \
            or manifest["schema_version"] != MODEL_MANIFEST_SCHEMA_VERSION:
        raise ModelRuntimeError("Unsupported model manifest schema version.")
    model_id = manifest["model_id"]
    if (not isinstance(model_id, str) or not _MODEL_ID.fullmatch(model_id)):
        raise ModelRuntimeError("model_id is invalid.")
    model_version = manifest["model_version"]
    if not isinstance(model_version, str) or not _VERSION.fullmatch(model_version):
        raise ModelRuntimeError("model_version must be an exact semantic version.")
    if expected_model_id is not None and model_id != expected_model_id:
        raise ModelRuntimeError("model_id does not match the frozen mission.")
    if expected_model_version is not None and model_version != expected_model_version:
        raise ModelRuntimeError("model_version does not match the frozen mission.")
    task = _text(manifest["task"], "task", limit=128)
    if task != "inspection_observation":
        raise ModelRuntimeError("Only task='inspection_observation' is supported.")

    runtime = _object(manifest["runtime"], "runtime", _RUNTIME_KEYS)
    runtime_name = _text(runtime["name"], "runtime.name", limit=64)
    if runtime_name != "python":
        raise ModelRuntimeError("runtime.name must be 'python'.")
    expected_runtime_version = runtime["version"]
    if (not isinstance(expected_runtime_version, str)
            or not _VERSION.fullmatch(expected_runtime_version)):
        raise ModelRuntimeError("runtime.version must be an exact semantic version.")
    if runtime_version is not None and runtime_version != expected_runtime_version:
        raise ModelRuntimeError(
            f"Model runtime version mismatch: expected {expected_runtime_version}, "
            f"found {runtime_version}."
        )
    entrypoint = runtime["entrypoint"]
    if not isinstance(entrypoint, str) or not _ENTRYPOINT.fullmatch(entrypoint):
        raise ModelRuntimeError("runtime.entrypoint must use module:function notation.")

    input_schema = _text(manifest["input_schema"], "input_schema", limit=128)
    output_schema = _text(manifest["output_schema"], "output_schema", limit=128)
    if input_schema != MODEL_INPUT_SCHEMA_VERSION:
        raise ModelRuntimeError("Unsupported model input schema.")
    if output_schema != MODEL_OUTPUT_SCHEMA_VERSION:
        raise ModelRuntimeError("Unsupported model output schema.")

    artifact = _validate_artifact(manifest_path, manifest["artifact"])
    if (expected_artifact_sha256 is not None
            and artifact.sha256 != expected_artifact_sha256):
        raise ModelRuntimeError("Model artifact SHA-256 does not match the frozen mission.")
    return ModelManifest(
        model_id=model_id,
        model_version=model_version,
        task=task,
        runtime_name=runtime_name,
        runtime_version=expected_runtime_version,
        entrypoint=entrypoint,
        input_schema=input_schema,
        output_schema=output_schema,
        artifact=artifact,
        manifest_sha256=manifest_sha256,
    )


def validate_model_input(payload: Any) -> dict[str, Any]:
    data = _object(payload, "model input", _INPUT_KEYS)
    if data["schema_version"] != MODEL_INPUT_SCHEMA_VERSION:
        raise ModelRuntimeError("Model input schema_version is unsupported.")
    for field in ("sample_id", "waypoint_id", "device_id"):
        _text(data[field], f"model input.{field}", limit=256)
    _utc_datetime(data["timestamp_utc"], "model input.timestamp_utc")

    provenance = _object(
        data["sensor_provenance"],
        "model input.sensor_provenance",
        _SENSOR_PROVENANCE_KEYS,
    )
    sensor_ids = provenance["sensor_ids"]
    if (
        not isinstance(sensor_ids, list)
        or not sensor_ids
        or len(set(sensor_ids)) != len(sensor_ids)
        or any(not isinstance(item, str) or not item.strip() for item in sensor_ids)
    ):
        raise ModelRuntimeError(
            "model input.sensor_provenance.sensor_ids must be unique non-empty strings."
        )
    _text(provenance["frame_id"], "model input.sensor_provenance.frame_id", limit=256)
    if not isinstance(data["features"], dict):
        raise ModelRuntimeError("model input.features must be an object.")
    _finite_json(data["features"], "model input.features")
    return data


def validate_model_output(
    payload: Any,
    *,
    expected_sample_id: str,
    expected_model_version: str,
) -> dict[str, Any]:
    data = _object(payload, "model output", _OUTPUT_KEYS)
    if data["schema_version"] != MODEL_OUTPUT_SCHEMA_VERSION:
        raise ModelRuntimeError("Model output schema_version is unsupported.")
    if data["sample_id"] != expected_sample_id:
        raise ModelRuntimeError("Model output sample_id does not match the input.")
    if data["model_version"] != expected_model_version:
        raise ModelRuntimeError("Model output model_version does not match the manifest.")
    _text(data["sample_id"], "model output.sample_id", limit=256)
    _text(data["model_version"], "model output.model_version", limit=128)
    if data["calibration_version"] is not None:
        _text(data["calibration_version"], "model output.calibration_version", limit=128)
    for field in ("pressure_mpa", "temperature_c", "ambient_temperature_c"):
        _finite_number(data[field], f"model output.{field}")
    for field in ("cabinet_door_closed", "leak_detected"):
        if data[field] is not None and not isinstance(data[field], bool):
            raise ModelRuntimeError(f"model output.{field} must be boolean or null.")
    confidence = data["sensor_confidence"]
    if not isinstance(confidence, dict):
        raise ModelRuntimeError("model output.sensor_confidence must be an object.")
    for sensor, score in confidence.items():
        if (
            not isinstance(sensor, str)
            or not sensor.strip()
            or isinstance(score, bool)
            or not isinstance(score, (int, float))
            or not math.isfinite(float(score))
            or not 0 <= score <= 1
        ):
            raise ModelRuntimeError(
                "model output.sensor_confidence values must be finite numbers in [0, 1]."
            )
    quality_flags = data["quality_flags"]
    if (
        not isinstance(quality_flags, list)
        or len(quality_flags) > 64
        or len(set(quality_flags)) != len(quality_flags)
        or any(not isinstance(flag, str) or not flag.strip() or len(flag) > 128
               for flag in quality_flags)
    ):
        raise ModelRuntimeError(
            "model output.quality_flags must be a list of unique non-empty strings."
        )
    _finite_number(data["inference_latency_ms"], "model output.inference_latency_ms")
    if data["inference_latency_ms"] is not None and data["inference_latency_ms"] < 0:
        raise ModelRuntimeError("model output.inference_latency_ms must be non-negative.")
    return data


def _load_entrypoint(entrypoint: str) -> Callable[[Path], ModelPredictor]:
    module_name, function_name = entrypoint.split(":", 1)
    try:
        factory = getattr(importlib.import_module(module_name), function_name)
    except (ImportError, AttributeError) as exc:
        raise ModelRuntimeError(
            f"Configured model runtime entrypoint cannot be loaded: {entrypoint}."
        ) from exc
    if not callable(factory):
        raise ModelRuntimeError("Configured model runtime entrypoint is not callable.")
    return factory


@dataclass(frozen=True)
class ModelRuntime:
    manifest: ModelManifest
    predictor: ModelPredictor

    @classmethod
    def load(
        cls,
        manifest_path: Path,
        *,
        runtime_version: str | None = None,
        expected_manifest_sha256: str | None = None,
        expected_artifact_sha256: str | None = None,
        expected_model_id: str | None = None,
        expected_model_version: str | None = None,
        entrypoint_loader: Callable[[str], Callable[[Path], ModelPredictor]] | None = None,
    ) -> "ModelRuntime":
        manifest = load_model_manifest(
            manifest_path,
            runtime_version=runtime_version or platform.python_version(),
            expected_manifest_sha256=expected_manifest_sha256,
            expected_artifact_sha256=expected_artifact_sha256,
            expected_model_id=expected_model_id,
            expected_model_version=expected_model_version,
        )
        factory = (entrypoint_loader or _load_entrypoint)(manifest.entrypoint)
        try:
            predictor = factory(manifest.artifact.path)
        except Exception as exc:
            raise ModelRuntimeError(
                "Model runtime could not initialize the configured artifact."
            ) from exc
        if not callable(predictor):
            raise ModelRuntimeError(
                "Model runtime factory must return a callable predictor."
            )
        return cls(manifest=manifest, predictor=predictor)

    def infer(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        validated_input = validate_model_input(payload)
        try:
            output = self.predictor(validated_input)
        except Exception as exc:
            # A model failure is terminal for this inference. Callers must not
            # replace it with a deterministic rule result without an explicit policy.
            raise ModelRuntimeError("Model inference failed; no fallback was applied.") from exc
        return validate_model_output(
            output,
            expected_sample_id=validated_input["sample_id"],
            expected_model_version=self.manifest.model_version,
        )
