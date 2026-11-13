from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import waypoints_from_config
from ..models import Observation, Severity
from ..perception.rules import RuleBasedDiagnosticEngine
from ..reporting import to_jsonable
from .artifact_storage import ArtifactStorage, ArtifactStorageError
from .entities import ArtifactRecord, MissionRecord, WorkOrderRecord
from .result_bundle import REQUIRED_ARTIFACT_MAX_BYTES, REQUIRED_RESULT_ARTIFACTS

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_MEDIA_TYPE = re.compile(r"^[A-Za-z0-9!#$&^_.+-]+/[A-Za-z0-9!#$&^_.+-]+$")
_RUN_KEYS = {
    "run_id", "site_id", "robot_id", "started_at_utc", "finished_at_utc",
    "status", "results", "source",
}
_WAYPOINT_RESULT_KEYS = {
    "waypoint_id", "device_id", "navigation_status", "inspection_status",
    "observation", "assessment", "work_order", "error",
}
_OBSERVATION_KEYS = {
    "sample_id", "timestamp_utc", "source", "robot_id", "waypoint_id",
    "device_id", "pressure_mpa", "temperature_c", "ambient_temperature_c",
    "cabinet_door_closed", "leak_detected", "sensor_confidence", "model_version",
    "calibration_version", "quality_flags", "inference_latency_ms", "domain",
}
_WORK_ORDER_KEYS = {
    "ticket_id", "created_at_utc", "site_id", "zone", "robot_id", "waypoint_id",
    "device_id", "device_name", "severity", "source", "observations",
    "anomaly_codes", "anomaly_messages", "recommended_actions", "requires_human_review",
}


class ResultValidationError(ValueError):
    def __init__(self, message: str, *, status_code: int = 422):
        super().__init__(message)
        self.status_code = status_code


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _object(value: Any, label: str, expected_keys: set[str] | None = None) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ResultValidationError(f"{label} must be an object.")
    if expected_keys is not None:
        missing = expected_keys - value.keys()
        extra = value.keys() - expected_keys
        if missing or extra:
            raise ResultValidationError(
                f"{label} fields do not match schema v1 (missing={sorted(missing)}, "
                f"extra={sorted(extra)})."
            )
    return value


def _text(value: Any, label: str, *, limit: int = 1024) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ResultValidationError(f"{label} must be a non-empty string of at most {limit} characters.")
    return value


def _utc_datetime(value: Any, label: str) -> datetime:
    if not isinstance(value, str):
        raise ResultValidationError(f"{label} must be an ISO-8601 UTC timestamp.")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    except ValueError as exc:
        raise ResultValidationError(f"{label} is not a valid ISO-8601 timestamp.") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise ResultValidationError(f"{label} must be normalized to UTC.")
    return parsed.astimezone(timezone.utc)


def _finite_json(value: Any, label: str) -> None:
    try:
        json.dumps(value, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ResultValidationError(f"{label} must contain finite JSON values only.") from exc


def _finite_number(value: Any, label: str) -> None:
    if value is None:
        return
    try:
        valid = not isinstance(value, bool) and isinstance(value, (int, float)) \
            and math.isfinite(float(value))
    except (OverflowError, ValueError):
        valid = False
    if not valid:
        raise ResultValidationError(f"{label} must be a finite number or null.")


def _validate_observation(
    raw: Any,
    *,
    mission: MissionRecord,
    frozen: dict[str, Any],
    expected_waypoint: Any,
    index: int,
    started_at: datetime,
    finished_at: datetime,
) -> Observation:
    data = _object(raw, "observation", _OBSERVATION_KEYS)
    expected = {
        "sample_id": f"{mission.run_id}-{index:03d}-{expected_waypoint.waypoint_id}",
        "source": frozen["source"],
        "robot_id": mission.robot_id,
        "waypoint_id": expected_waypoint.waypoint_id,
        "device_id": expected_waypoint.device_id,
    }
    for field, expected_value in expected.items():
        if data.get(field) != expected_value:
            raise ResultValidationError(f"observation.{field} does not match the frozen mission.")
    for field in ("sample_id", "source", "robot_id", "waypoint_id", "device_id"):
        _text(data[field], f"observation.{field}")

    observed_at = _utc_datetime(data["timestamp_utc"], "observation.timestamp_utc")
    if not started_at <= observed_at <= finished_at:
        raise ResultValidationError("Observation timestamp is outside the inspection run.")
    for field in ("pressure_mpa", "temperature_c", "ambient_temperature_c"):
        _finite_number(data[field], f"observation.{field}")
    for field in ("cabinet_door_closed", "leak_detected"):
        if data[field] is not None and not isinstance(data[field], bool):
            raise ResultValidationError(f"observation.{field} must be boolean or null.")

    for field in ("model_version", "calibration_version"):
        value = data[field]
        if value is not None:
            _text(value, f"observation.{field}", limit=128)
    quality_flags = data["quality_flags"]
    if (not isinstance(quality_flags, list) or len(quality_flags) > 64
            or any(not isinstance(flag, str) or not flag.strip() or len(flag) > 128
                   for flag in quality_flags)
            or len(set(quality_flags)) != len(quality_flags)):
        raise ResultValidationError(
            "observation.quality_flags must be a list of unique non-empty strings."
        )
    _finite_number(data["inference_latency_ms"], "observation.inference_latency_ms")
    if (data["inference_latency_ms"] is not None
            and data["inference_latency_ms"] < 0):
        raise ResultValidationError("observation.inference_latency_ms must be non-negative.")

    confidence = _object(data["sensor_confidence"], "observation.sensor_confidence")
    for sensor, score in confidence.items():
        try:
            valid_score = (not isinstance(score, bool) and isinstance(score, (int, float))
                           and math.isfinite(float(score)) and 0 <= score <= 1)
        except (OverflowError, ValueError):
            valid_score = False
        if not isinstance(sensor, str) or not sensor.strip() or not valid_score:
            raise ResultValidationError(
                "observation.sensor_confidence values must be finite numbers in [0, 1]."
            )
    domain = _object(data["domain"], "observation.domain")
    _finite_json(domain, "observation.domain")

    if frozen["source"] == "isaac_sim":
        sensor_provenance = _object(domain.get("sensor_provenance"),
                                    "observation.domain.sensor_provenance")
        sensor_ids = sensor_provenance.get("sensor_ids")
        if (not isinstance(sensor_ids, list) or not sensor_ids
                or any(not isinstance(sensor_id, str) or not sensor_id.strip()
                       for sensor_id in sensor_ids)
                or len(set(sensor_ids)) != len(sensor_ids)):
            raise ResultValidationError("Isaac observation must identify unique sensor streams.")
        _text(sensor_provenance.get("frame_id"), "observation.domain.sensor_provenance.frame_id")

        simulator = _object(frozen.get("simulator"), "frozen simulator configuration")
        provenance = _object(domain.get("simulation_provenance"),
                             "observation.domain.simulation_provenance", {
                                 "runtime", "runtime_version", "seed", "manifest_sha256",
                                 "robot_usd_path",
                             })
        expected_provenance = {
            "runtime": "Isaac Sim",
            "runtime_version": simulator.get("expected_version"),
            "seed": mission.seed,
            "manifest_sha256": hashlib.sha256(
                mission.manifest_json.encode("utf-8")).hexdigest(),
            "robot_usd_path": simulator.get("robot_usd_path"),
        }
        if provenance != expected_provenance:
            raise ResultValidationError(
                "Isaac simulation provenance does not match the frozen mission manifest."
            )
        if (data["temperature_c"] is not None
                and domain.get("temperature_semantics") != "simulated_proxy"):
            raise ResultValidationError(
                "Isaac temperature readings must be marked simulated_proxy."
            )
        model_config = simulator.get("model")
        if model_config is not None:
            model_config = _object(model_config, "frozen model configuration", {
                "manifest_path", "manifest_sha256", "artifact_sha256", "model_id",
                "model_version",
            })
            model_provenance = _object(domain.get("model_provenance"),
                                       "observation.domain.model_provenance", {
                                           "model_id", "model_version", "manifest_sha256",
                                           "artifact_sha256", "input_schema", "output_schema",
                                       })
            if model_provenance != {
                "model_id": model_config["model_id"],
                "model_version": model_config["model_version"],
                "manifest_sha256": model_config["manifest_sha256"],
                "artifact_sha256": model_config["artifact_sha256"],
                "input_schema": "inspection-model-input/v1",
                "output_schema": "inspection-model-output/v1",
            } or data["model_version"] != model_config["model_version"]:
                raise ResultValidationError(
                    "Model provenance does not match the frozen mission configuration."
                )
        elif data["model_version"] is not None:
            raise ResultValidationError(
                "Isaac observation contains model_version without a frozen model configuration."
            )

    try:
        return Observation(**data)
    except TypeError as exc:
        raise ResultValidationError("Observation does not match schema v1.") from exc


def _validate_artifacts(
    session: Session,
    storage: ArtifactStorage,
    run_id: str,
    source: str,
    descriptors: Any,
    inspection_run: dict[str, Any],
) -> None:
    if not isinstance(descriptors, list) or not descriptors:
        raise ResultValidationError("Result manifest must describe its result artifacts.")
    by_name: dict[str, dict[str, Any]] = {}
    for value in descriptors:
        item = _object(value, "artifact descriptor", {"name", "sha256", "size_bytes"})
        name = _text(item["name"], "artifact.name", limit=255)
        digest = item["sha256"]
        size = item["size_bytes"]
        if not isinstance(digest, str) or not _SHA256.fullmatch(digest):
            raise ResultValidationError(f"Artifact {name} has an invalid SHA-256 value.")
        if isinstance(size, bool) or not isinstance(size, int) or size < 0:
            raise ResultValidationError(f"Artifact {name} has an invalid size.")
        if name in by_name:
            raise ResultValidationError(f"Duplicate artifact descriptor: {name}.")
        max_size = REQUIRED_ARTIFACT_MAX_BYTES.get(name)
        if max_size is not None and size > max_size:
            raise ResultValidationError(
                f"Required metadata artifact {name} exceeds its {max_size}-byte limit."
            )
        by_name[name] = item
    missing = REQUIRED_RESULT_ARTIFACTS - by_name.keys()
    if missing:
        raise ResultValidationError(f"Required result artifacts are missing: {sorted(missing)}.")
    if sum(item["size_bytes"] for item in by_name.values()) > storage.max_bytes:
        raise ResultValidationError("Result artifacts exceed the configured total size limit.")

    started_at = _utc_datetime(
        inspection_run.get("started_at_utc"), "inspection_run.started_at_utc")
    finished_at = _utc_datetime(
        inspection_run.get("finished_at_utc"), "inspection_run.finished_at_utc")
    referenced: set[str] = set()
    for index, result in enumerate(inspection_run.get("results", [])):
        if not isinstance(result, dict):
            raise ResultValidationError(f"results[{index}] must be an object.")
        observation = result.get("observation")
        if observation is None:
            continue
        if not isinstance(observation, dict):
            raise ResultValidationError(f"results[{index}].observation must be an object.")
        domain = observation.get("domain")
        if not isinstance(domain, dict):
            continue
        provenance = domain.get("sensor_provenance")
        if provenance is None:
            continue
        if not isinstance(provenance, dict):
            raise ResultValidationError("sensor_provenance must be an object.")
        sensor_ids = provenance.get("sensor_ids")
        artifact_refs = provenance.get("artifacts", [])
        if not isinstance(artifact_refs, list):
            raise ResultValidationError("sensor_provenance.artifacts must be a list.")
        for ref in artifact_refs:
            metadata = _object(ref, "sensor artifact reference", {
                "name", "sensor_id", "media_type", "timestamp_utc",
            })
            name = _text(metadata["name"], "sensor artifact name", limit=255)
            sensor_id = _text(metadata["sensor_id"], "sensor artifact sensor_id", limit=128)
            media_type = _text(metadata["media_type"], "sensor artifact media_type", limit=127)
            if not _MEDIA_TYPE.fullmatch(media_type):
                raise ResultValidationError("Sensor artifact media_type is invalid.")
            if not isinstance(sensor_ids, list) or sensor_id not in sensor_ids:
                raise ResultValidationError("Sensor artifact references an unknown sensor stream.")
            if name in REQUIRED_RESULT_ARTIFACTS or name not in by_name:
                raise ResultValidationError(f"Sensor artifact file is not declared: {name}.")
            if name in referenced:
                raise ResultValidationError(f"Sensor artifact is referenced more than once: {name}.")
            captured_at = _utc_datetime(metadata["timestamp_utc"],
                                        "sensor artifact timestamp_utc")
            if not started_at <= captured_at <= finished_at:
                raise ResultValidationError("Sensor artifact timestamp is outside the inspection run.")
            referenced.add(name)
    unreferenced = (by_name.keys() - REQUIRED_RESULT_ARTIFACTS) - referenced
    if unreferenced:
        raise ResultValidationError(
            f"Sensor artifacts have no observation reference: {sorted(unreferenced)}."
        )

    contents: dict[str, bytes] = {}
    for name, descriptor in by_name.items():
        record = session.scalar(select(ArtifactRecord).where(
            ArtifactRecord.run_id == run_id, ArtifactRecord.name == name))
        if (record is None or record.source != source
                or record.sha256 != descriptor["sha256"]
                or record.size_bytes != descriptor["size_bytes"]):
            raise ResultValidationError(f"Artifact is not uploaded or metadata mismatch: {name}.")
        if not storage.validate_reference(record.storage_path, run_id, descriptor["sha256"]):
            raise ResultValidationError(f"Artifact storage path is not content-addressed: {name}.")
        if name in REQUIRED_RESULT_ARTIFACTS:
            try:
                content = storage.read_bytes(record.storage_path)
            except ArtifactStorageError:
                raise
            actual_size = len(content)
            actual_digest = hashlib.sha256(content).hexdigest()
            if actual_size != descriptor["size_bytes"] or actual_digest != descriptor["sha256"]:
                raise ResultValidationError(
                    f"Stored artifact content failed integrity check: {name}."
                )
            contents[name] = content
        elif not storage.verify_artifact(
                record.storage_path, run_id, descriptor["sha256"], descriptor["size_bytes"]):
            raise ResultValidationError(
                f"Stored artifact content failed integrity check: {name}."
            )

    try:
        archived_run = json.loads(contents["inspection_run.json"])
        archived_orders = json.loads(contents["work_orders.json"])
        archived_report = contents["inspection_report.md"].decode("utf-8")[:256 * 1024]
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ResultValidationError("Result artifacts are not valid UTF-8 JSON/Markdown.") from exc
    if canonical_json(archived_run) != canonical_json(inspection_run):
        raise ResultValidationError("inspection_run.json does not match the imported result.")
    expected_orders = [item["work_order"] for item in inspection_run["results"]
                       if item["work_order"] is not None]
    if canonical_json(archived_orders) != canonical_json(expected_orders):
        raise ResultValidationError("work_orders.json does not match the imported result.")
    if inspection_run["run_id"] not in archived_report:
        raise ResultValidationError("Inspection report does not identify the imported run.")


def persist_inspection_result(
    session: Session,
    mission: MissionRecord,
    manifest: dict[str, Any],
    inspection_run: dict[str, Any],
    storage: ArtifactStorage,
) -> tuple[bool, str]:
    run_id = mission.run_id
    manifest = _object(manifest, "result manifest", {
        "schema_version", "run_id", "source", "software_version", "config_sha256", "artifacts",
    })
    inspection_run = _object(inspection_run, "inspection_run")
    if manifest.get("run_id") != run_id or inspection_run.get("run_id") != run_id:
        raise ResultValidationError("run_id mismatch.", status_code=409)
    frozen = json.loads(mission.manifest_json)
    if frozen.get("schema_version") != 1:
        raise ResultValidationError("Frozen mission manifest has an unsupported schema version.")
    if frozen.get("seed") != mission.seed:
        raise ResultValidationError("Frozen manifest seed does not match the mission record.",
                                    status_code=409)
    if manifest.get("config_sha256") != frozen.get("config_sha256"):
        raise ResultValidationError("Configuration hash mismatch.", status_code=409)
    if manifest.get("source") != inspection_run.get("source"):
        raise ResultValidationError("Result source does not match manifest.", status_code=409)
    if manifest.get("source") != frozen.get("source"):
        raise ResultValidationError("Result source does not match submitted mission.",
                                    status_code=409)
    if inspection_run.get("site_id") != mission.site_id:
        raise ResultValidationError("Result site_id does not match the mission.")
    if inspection_run.get("robot_id") != mission.robot_id:
        raise ResultValidationError("Result robot_id does not match the mission.")
    if type(manifest.get("schema_version")) is not int or manifest["schema_version"] != 1:
        raise ResultValidationError("Unsupported result schema version.")
    software_version = _text(manifest.get("software_version"), "software_version", limit=64)
    source = frozen.get("source")
    if not isinstance(source, str) or not source.strip():
        raise ResultValidationError("Frozen mission source is invalid.")
    if source == "isaac_sim":
        simulator = _object(frozen.get("simulator"), "frozen simulator configuration")
        expected_software_version = f"isaac-sim/{simulator.get('expected_version')}"
        if software_version != expected_software_version:
            raise ResultValidationError("Isaac runtime version does not match the result manifest.")
    elif software_version != frozen.get("software_version"):
        raise ResultValidationError("Result software version does not match the frozen mission.")

    site_config = _object(frozen.get("site_config"), "frozen site configuration")
    if site_config.get("site_id") != mission.site_id:
        raise ResultValidationError("Frozen site configuration does not match the mission.")
    robot = _object(site_config.get("robot"), "frozen robot configuration")
    if robot.get("robot_id") != mission.robot_id:
        raise ResultValidationError("Frozen robot configuration does not match the mission.")
    if sha256_json(site_config) != frozen.get("config_sha256"):
        raise ResultValidationError("Frozen site configuration checksum is invalid.",
                                    status_code=409)
    waypoint_ids = frozen.get("waypoint_ids")
    if (not isinstance(waypoint_ids, list) or not waypoint_ids
            or any(not isinstance(item, str) or not item for item in waypoint_ids)
            or len(set(waypoint_ids)) != len(waypoint_ids)):
        raise ResultValidationError("Frozen waypoint list is invalid.")
    try:
        waypoints = waypoints_from_config(site_config)
    except (KeyError, TypeError, ValueError) as exc:
        raise ResultValidationError("Frozen waypoint configuration is invalid.") from exc
    if [item.waypoint_id for item in waypoints] != waypoint_ids:
        raise ResultValidationError("Frozen waypoint order does not match site configuration.")

    run_data = _object(inspection_run, "inspection_run", _RUN_KEYS)
    _finite_json(run_data, "inspection_run")
    if run_data["source"] != source:
        raise ResultValidationError("inspection_run.source does not match the frozen mission.",
                                    status_code=409)
    started_at = _utc_datetime(run_data["started_at_utc"], "inspection_run.started_at_utc")
    finished_at = _utc_datetime(run_data["finished_at_utc"], "inspection_run.finished_at_utc")
    if finished_at < started_at:
        raise ResultValidationError("Inspection run finished before it started.")
    results = run_data["results"]
    if not isinstance(results, list) or len(results) != len(waypoints):
        raise ResultValidationError(
            "Result must contain exactly one record for every frozen waypoint in order."
        )
    if len(results) > 1000:
        raise ResultValidationError("Result contains too many waypoint records.")
    run_status = _text(run_data["status"], "inspection_run.status", limit=64)
    if run_status not in {"COMPLETED", "COMPLETED_WITH_ERRORS"}:
        raise ResultValidationError("Unsupported inspection run status.")

    expected_orders: list[dict[str, Any]] = []
    ticket_ids: set[str] = set()
    engine = RuleBasedDiagnosticEngine()
    all_completed = True
    for index, (item_value, waypoint) in enumerate(zip(results, waypoints, strict=True), start=1):
        item = _object(item_value, f"results[{index - 1}]", _WAYPOINT_RESULT_KEYS)
        if item["waypoint_id"] != waypoint.waypoint_id:
            raise ResultValidationError("Waypoint result order/identity does not match the mission.")
        if item["device_id"] != waypoint.device_id:
            raise ResultValidationError("Waypoint device_id does not match the frozen mission.")
        navigation = _text(item["navigation_status"],
                           f"results[{index - 1}].navigation_status", limit=64)
        inspection = _text(item["inspection_status"],
                           f"results[{index - 1}].inspection_status", limit=64)
        if navigation not in {"SUCCEEDED", "FAILED", "SKIPPED"}:
            raise ResultValidationError("Unsupported navigation status.")
        if inspection not in {"COMPLETED", "FAILED", "SKIPPED"}:
            raise ResultValidationError("Unsupported waypoint inspection status.")
        error = item["error"]
        if error is not None:
            _text(error, f"results[{index - 1}].error", limit=1000)

        successful_waypoint = navigation == "SUCCEEDED" and inspection == "COMPLETED"
        if not successful_waypoint:
            all_completed = False
            if error is None:
                raise ResultValidationError("Failed or skipped waypoint must include an error reason.")
            if item["observation"] is not None or item["assessment"] is not None or item["work_order"] is not None:
                raise ResultValidationError("Failed or skipped waypoint cannot include derived inspection data.")
            if navigation == "FAILED" and inspection not in {"FAILED", "SKIPPED"}:
                raise ResultValidationError("Failed navigation must fail or skip inspection.")
            if navigation == "SKIPPED" and inspection != "SKIPPED":
                raise ResultValidationError("Skipped navigation must skip inspection.")
            if navigation == "SUCCEEDED" and inspection not in {"FAILED", "SKIPPED"}:
                raise ResultValidationError("Waypoint execution state is inconsistent.")
            continue

        if error is not None or item["observation"] is None or item["assessment"] is None:
            raise ResultValidationError("Completed inspection requires observation and assessment data.")
        observation = _validate_observation(
            item["observation"], mission=mission, frozen=frozen,
            expected_waypoint=waypoint, index=index,
            started_at=started_at, finished_at=finished_at,
        )
        assessment = engine.assess(observation, waypoint)
        expected_assessment = to_jsonable(assessment)
        if canonical_json(item["assessment"]) != canonical_json(expected_assessment):
            raise ResultValidationError("Waypoint assessment does not match deterministic rule output.")
        if assessment.severity == Severity.NORMAL and item["work_order"] is None:
            continue
        if item["work_order"] is None:
            raise ResultValidationError("Non-normal observation requires its rule-generated work order.")
        expected_order = to_jsonable(engine.create_work_order(
            observation, waypoint, assessment, mission.site_id, run_id=run_id,
        ))
        order = _object(item["work_order"], f"results[{index - 1}].work_order", _WORK_ORDER_KEYS)
        created_at = _utc_datetime(order["created_at_utc"], "work_order.created_at_utc")
        if not started_at <= created_at <= finished_at:
            raise ResultValidationError("Work-order timestamp is outside the inspection run.")
        expected_order["created_at_utc"] = order["created_at_utc"]
        if canonical_json(order) != canonical_json(expected_order):
            raise ResultValidationError("Work order does not match its observation and assessment.")
        ticket_id = _text(order["ticket_id"], "work_order.ticket_id", limit=128)
        if ticket_id in ticket_ids:
            raise ResultValidationError("Duplicate work-order ticket_id in result.")
        ticket_ids.add(ticket_id)
        expected_orders.append(order)

    expected_status = "COMPLETED" if all_completed else "COMPLETED_WITH_ERRORS"
    if run_data["status"] != expected_status:
        raise ResultValidationError("Inspection run status does not match waypoint outcomes.")

    _validate_artifacts(
        session, storage, run_id, source, manifest.get("artifacts"), run_data,
    )

    result_hash = sha256_json(run_data)
    if mission.result_hash and mission.result_hash != result_hash:
        raise ResultValidationError("A different result is already imported.", status_code=409)

    for order in expected_orders:
        ticket_id = order["ticket_id"]
        payload = canonical_json(order)
        existing = session.get(WorkOrderRecord, ticket_id)
        if existing and (existing.run_id != run_id or existing.payload_json != payload):
            raise ResultValidationError("Work order ticket_id conflict.", status_code=409)
    for order in expected_orders:
        ticket_id = order["ticket_id"]
        if session.get(WorkOrderRecord, ticket_id) is None:
            session.add(WorkOrderRecord(
                ticket_id=ticket_id,
                run_id=run_id,
                severity=order["severity"],
                review_status="PENDING",
                payload_json=canonical_json(order),
            ))

    if mission.result_hash:
        return True, result_hash
    mission.result_json = canonical_json(run_data)
    mission.result_hash = result_hash
    mission.status = "PARTIAL" if run_status == "COMPLETED_WITH_ERRORS" else "SUCCEEDED"
    mission.error = None
    mission.finished_at = datetime.now(timezone.utc)
    return False, result_hash
