#!/usr/bin/env python3
"""Seed a local demo database from an already rendered Blender scene.

The renderer produces a large, immutable scene bundle. This importer keeps the
local demo startup fast by reusing that bundle while borrowing the validated
inspection result structure from a previous industrial replay.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import uuid

from sqlalchemy import select

from inspection_system.platform.artifact_storage import LocalArtifactStorage
from inspection_system.platform.artifact_store import store_artifact_bytes, store_artifact_file
from inspection_system.config import waypoints_from_config
from inspection_system.platform.db import create_database
from inspection_system.platform.entities import ArtifactRecord, AuditEventRecord, MissionRecord
from inspection_system.models import Observation
from inspection_system.perception.rules import RuleBasedDiagnosticEngine
from inspection_system.platform.result_service import canonical_json, persist_inspection_result, sha256_json
from inspection_system.platform.result_bundle import REQUIRED_RESULT_ARTIFACTS
from inspection_system.platform.db import Base
from inspection_system.reporting import to_jsonable


DEFAULT_RUN_ID = "RUN-V23-HIGHGRANULARITY"
SOURCE_RUN_ID = "RUN-B97F9E32E8DE4852"
REQUIRED_FROM_SOURCE = {
    "inspection_run.json",
    "inspection_report.md",
    "scene_input.json",
    "trajectory.json",
    "work_orders.json",
}
SCENARIOS = ("source", "successful", "synthetic_anomaly")


def _artifact_media_type(name: str) -> str:
    suffix = Path(name).suffix.lower()
    return {
        ".png": "image/png",
        ".svg": "image/svg+xml",
        ".json": "application/json",
        ".glb": "model/gltf-binary",
        ".blend": "application/octet-stream",
        ".mp4": "video/mp4",
        ".webm": "video/webm",
        ".m3u8": "application/vnd.apple.mpegurl",
    }.get(suffix, "application/octet-stream")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _replace_run_id(value: object, old_run_id: str, new_run_id: str) -> object:
    if isinstance(value, str):
        return value.replace(old_run_id, new_run_id)
    if isinstance(value, list):
        return [_replace_run_id(item, old_run_id, new_run_id) for item in value]
    if isinstance(value, dict):
        return {
            str(key): _replace_run_id(item, old_run_id, new_run_id)
            for key, item in value.items()
        }
    return value


def _successful_demo_observation(
    raw_observation: object,
    *,
    waypoint,
    robot_id: str,
    run_id: str,
    index: int,
    render_resolution: int,
    render_quality: str,
) -> dict:
    """Build a complete, in-range observation for the product demo scenario."""
    if not isinstance(raw_observation, dict):
        raise RuntimeError("Successful demo requires an observation for every waypoint.")
    observation = deepcopy(raw_observation)
    pressure_limit = waypoint.pressure_max_mpa
    pressure = (
        0.35 if pressure_limit is None
        else round(max(0.1, min(pressure_limit * 0.72, pressure_limit - 0.05)), 3)
    )
    temperature = round(max(20.0, min(
        waypoint.warning_temp_c - 5.0,
        waypoint.critical_temp_c - 12.0,
        42.0,
    )), 1)
    observation.update({
        "sample_id": f"{run_id}-{index:03d}-{waypoint.waypoint_id}",
        "source": "synthetic_simulation",
        "robot_id": robot_id,
        "waypoint_id": waypoint.waypoint_id,
        "device_id": waypoint.device_id,
        "pressure_mpa": pressure,
        "temperature_c": temperature,
        "ambient_temperature_c": 24.0,
        "cabinet_door_closed": True,
        "leak_detected": False,
        "sensor_confidence": {
            "rgb_camera": 0.98,
            "thermal_camera": 0.97,
            "pressure_gateway": 0.96,
            "state": 0.99,
        },
        "quality_flags": ["SYNTHETIC_INPUT", "SUCCESSFUL_DEMO_SCENARIO"],
    })
    domain = observation.setdefault("domain", {})
    if not isinstance(domain, dict):
        domain = {}
        observation["domain"] = domain
    domain.update({
        "scenario": "successful_demo",
        "demo_scenario": "all_normal",
        "rendered_image_available": True,
        "render_quality": render_quality,
        "render_resolution": render_resolution,
    })
    return observation


def _synthetic_anomaly_observation(
    raw_observation: object,
    *,
    waypoint,
    robot_id: str,
    run_id: str,
    index: int,
    render_resolution: int,
    render_quality: str,
) -> dict:
    """Build an isolated, deterministic anomaly branch for product closeout demos."""
    if not isinstance(raw_observation, dict):
        raise RuntimeError("Synthetic anomaly demo requires an observation for every waypoint.")
    observation = deepcopy(raw_observation)
    pressure_limit = waypoint.pressure_max_mpa
    pressure = (
        None if pressure_limit is None
        else round(pressure_limit * 0.72, 3)
    )
    temperature = round(max(24.0, waypoint.warning_temp_c - 8.0), 1)
    cabinet_door_closed = True if waypoint.require_door_closed else None
    leak_detected = False

    # Keep the anomaly pattern stable so a recorded demo always shows the same
    # rule findings while the untouched V37 success run remains all-normal.
    if waypoint.waypoint_id == "WP_01_PIPE":
        pressure = round((pressure_limit or 1.0) * 1.21, 3)
        temperature = round(max(waypoint.critical_temp_c + 5.0, 68.0), 1)
    elif waypoint.waypoint_id == "WP_02_VESSEL":
        pressure = round((pressure_limit or 1.0) * 1.08, 3)
        temperature = round(max(24.0, waypoint.warning_temp_c - 4.0), 1)
    elif waypoint.waypoint_id == "WP_03_CABINET":
        pressure = None
        temperature = round(max(waypoint.critical_temp_c + 4.0, 66.0), 1)
        cabinet_door_closed = False
    elif waypoint.waypoint_id == "WP_04_PUMP":
        pressure = round((pressure_limit or 1.0) * 1.24, 3)
        temperature = round(max(24.0, waypoint.warning_temp_c + 2.0), 1)
        leak_detected = True
    elif waypoint.waypoint_id == "WP_05_EXCHANGER":
        pressure = None
        temperature = round(max(24.0, waypoint.warning_temp_c - 7.0), 1)

    observation.update({
        "sample_id": f"{run_id}-{index:03d}-{waypoint.waypoint_id}",
        "source": "synthetic_simulation",
        "robot_id": robot_id,
        "waypoint_id": waypoint.waypoint_id,
        "device_id": waypoint.device_id,
        "pressure_mpa": pressure,
        "temperature_c": temperature,
        "ambient_temperature_c": 24.0,
        "cabinet_door_closed": cabinet_door_closed,
        "leak_detected": leak_detected,
        "sensor_confidence": {
            "rgb_camera": 0.98,
            "thermal_camera": 0.96,
            "pressure_gateway": 0.0 if pressure is None else 0.94,
            "state": 0.94 if cabinet_door_closed is not None else 0.0,
        },
        "quality_flags": ["SYNTHETIC_INPUT", "ANOMALY_DEMO_SCENARIO"],
    })
    domain = observation.setdefault("domain", {})
    if not isinstance(domain, dict):
        domain = {}
        observation["domain"] = domain
    domain.update({
        "scenario": "synthetic_anomaly",
        "demo_scenario": "isolated_synthetic_anomaly",
        "rendered_image_available": True,
        "render_quality": render_quality,
        "render_resolution": render_resolution,
    })
    return observation


def _render_successful_demo_report(
    result: dict,
    *,
    scene_detail_level: str,
) -> bytes:
    results = result.get("results", [])
    normal_count = sum(
        (item.get("assessment") or {}).get("severity") == "NORMAL"
        for item in results
    )
    lines = [
        "# 工业巡检产品成功演示报告",
        "",
        f"- **运行编号**：`{result['run_id']}`",
        f"- **站点**：`{result['site_id']}`",
        f"- **机器人**：`{result['robot_id']}`",
        f"- **状态**：`{result['status']}`",
        f"- **开始时间（UTC）**：{result['started_at_utc']}",
        f"- **结束时间（UTC）**：{result['finished_at_utc']}",
        f"- **数据来源**：`{result['source']}`",
        f"- **场景版本**：`{scene_detail_level}`",
        "",
        "> 本报告用于本机虚拟工厂产品演示。观测、图像流和机器人运动均为合成仿真，不能替代现场传感器、真实机器狗或工业验收。",
        "",
        "## 演示验收摘要",
        "",
        f"- 航点导航：**{sum(item.get('navigation_status') == 'SUCCEEDED' for item in results)}/{len(results)} 成功**",
        f"- 点位巡检：**{sum(item.get('inspection_status') == 'COMPLETED' for item in results)}/{len(results)} 完成**",
        f"- 正常评估：**{normal_count}/{len(results)}**",
        "- 规则告警：**0**",
        "- 待复核工单：**0**",
        "- 机器人 RGB 与仓库 CCTV：使用同一条路线时间轴同步回放",
        "",
        "## 航点结果",
        "",
        "| 航点 | 设备 | 导航 | 巡检 | 评估 | 异常代码 |",
        "|---|---|---|---|---|---|",
    ]
    for item in results:
        assessment = item.get("assessment") or {}
        lines.append(
            f"| {item['waypoint_id']} | {item['device_id']} | "
            f"{item['navigation_status']} | {item['inspection_status']} | "
            f"{assessment.get('severity', 'UNKNOWN')} | - |"
        )
    lines.extend([
        "",
        "## 产品边界",
        "",
        "本次成功态由站点配置阈值、完整合成观测和确定性规则引擎共同计算得到。",
        "系统保留 3D 工厂、多机位、机器人头顶 RGB、固定仓库 CCTV、路线和结果制品，",
        "便于演示产品闭环；接入真实设备前仍需完成现场坐标、传感器、标定、网络和安全验收。",
        "",
    ])
    return "\n".join(lines).encode("utf-8")


def _render_synthetic_anomaly_report(
    result: dict,
    *,
    scene_detail_level: str,
) -> bytes:
    results = result.get("results", [])
    orders = [
        item.get("work_order")
        for item in results
        if isinstance(item, dict) and item.get("work_order") is not None
    ]
    critical_count = sum(
        (item.get("assessment") or {}).get("severity") == "CRITICAL"
        for item in results
    )
    warning_count = sum(
        (item.get("assessment") or {}).get("severity") == "WARNING"
        for item in results
    )
    unknown_count = sum(
        (item.get("assessment") or {}).get("severity") == "UNKNOWN"
        for item in results
    )
    lines = [
        "# 工业巡检产品合成异常闭环报告",
        "",
        f"- **运行编号**：`{result['run_id']}`",
        f"- **站点**：`{result['site_id']}`",
        f"- **机器人**：`{result['robot_id']}`",
        f"- **状态**：`{result['status']}`",
        f"- **开始时间（UTC）**：{result['started_at_utc']}",
        f"- **结束时间（UTC）**：{result['finished_at_utc']}",
        f"- **数据来源**：`{result['source']}`",
        f"- **场景版本**：`{scene_detail_level}`",
        "",
        "> 本报告是隔离的本地合成异常分支，用于演示规则告警、人工复核、工单和审计闭环。它不代表真实现场测量，不调用真实 EAM，也不触发任何现场动作。",
        "",
        "## 演示验收摘要",
        "",
        f"- 航点导航：**{sum(item.get('navigation_status') == 'SUCCEEDED' for item in results)}/{len(results)} 成功**",
        f"- 点位巡检：**{sum(item.get('inspection_status') == 'COMPLETED' for item in results)}/{len(results)} 完成**",
        f"- 严重告警：**{critical_count}**",
        f"- 预警关注：**{warning_count}**",
        f"- 数据不足：**{unknown_count}**",
        f"- 待复核工单：**{len(orders)}**",
        "- 处置边界：人工确认后才允许管理员显式调用可选 EAM 适配器",
        "",
        "## 航点结果",
        "",
        "| 航点 | 设备 | 评估 | 异常代码 | 工单 |",
        "|---|---|---|---|---|",
    ]
    for item in results:
        assessment = item.get("assessment") or {}
        anomalies = assessment.get("anomalies") or []
        codes = ", ".join(
            anomaly.get("code", "UNKNOWN")
            for anomaly in anomalies
            if isinstance(anomaly, dict)
        ) or "-"
        order = item.get("work_order") or {}
        lines.append(
            f"| {item['waypoint_id']} | {item['device_id']} | "
            f"{assessment.get('severity', 'UNKNOWN')} | {codes} | "
            f"{order.get('ticket_id', '-')} |"
        )
    lines.extend([
        "",
        "## 产品边界",
        "",
        "该分支复用同一套 Blender 工厂、碰撞安全路线、机器人头顶 RGB、固定仓库 CCTV 和同步时间轴，仅替换本地观测值以触发确定性规则。",
        "复核完成后可展示审计记录；EAM 适配器默认未接入，因此不会产生外部工单或现场动作。",
        "",
    ])
    return "\n".join(lines).encode("utf-8")


def _read_source_artifacts(source_db: Path, source_run_id: str) -> tuple[dict, dict[str, bytes]]:
    engine, session_factory = create_database(
        f"sqlite:///{source_db}", environment="local_demo")
    try:
        with session_factory() as session:
            mission = session.get(MissionRecord, source_run_id)
            if mission is None or not mission.result_json:
                raise RuntimeError(f"Source mission {source_run_id} has no imported result.")
            result = json.loads(mission.result_json)
            records = session.scalars(select(ArtifactRecord).where(
                ArtifactRecord.run_id == source_run_id,
            )).all()
            artifacts: dict[str, bytes] = {}
            for record in records:
                path = Path(record.storage_path)
                if not path.is_file():
                    raise RuntimeError(f"Source artifact is unavailable: {record.name}")
                artifacts[record.name] = path.read_bytes()
            return result, artifacts
    finally:
        engine.dispose()


def _build_artifact_payload(
    *,
    scene_dir: Path,
    source_artifacts: dict[str, bytes],
    result: dict,
    site_config: dict,
    old_run_id: str,
    new_run_id: str,
    scenario: str,
    scene_detail_level: str,
    render_resolution: int,
    render_quality: str,
) -> dict[str, bytes | Path]:
    payload: dict[str, bytes | Path] = {}
    for path in sorted(scene_dir.iterdir()):
        # The runtime keeps this bookkeeping manifest outside the uploaded
        # artifact set because it has no observation provenance reference.
        if (path.is_file() and not path.name.startswith("._")
                and path.name != "virtual_world_manifest.json"):
            payload[path.name] = path

    rewritten_result = _replace_run_id(result, old_run_id, new_run_id)
    if not isinstance(rewritten_result, dict):
        raise RuntimeError("Source result is not a JSON object.")
    waypoints = waypoints_from_config(site_config)
    engine = RuleBasedDiagnosticEngine()
    result_items = rewritten_result.get("results", [])
    if not isinstance(result_items, list) or len(result_items) != len(waypoints):
        raise RuntimeError("Source result waypoint count does not match the site config.")
    for index, (item, waypoint) in enumerate(zip(result_items, waypoints, strict=True), start=1):
        if not isinstance(item, dict):
            raise RuntimeError("Source result contains an invalid waypoint result.")
        observation = item.get("observation") if isinstance(item, dict) else None
        if scenario == "successful":
            observation = _successful_demo_observation(
                observation,
                waypoint=waypoint,
                robot_id=str(rewritten_result["robot_id"]),
                run_id=new_run_id,
                index=index,
                render_resolution=render_resolution,
                render_quality=render_quality,
            )
            item["observation"] = observation
        elif scenario == "synthetic_anomaly":
            observation = _synthetic_anomaly_observation(
                observation,
                waypoint=waypoint,
                robot_id=str(rewritten_result["robot_id"]),
                run_id=new_run_id,
                index=index,
                render_resolution=render_resolution,
                render_quality=render_quality,
            )
            item["observation"] = observation
        domain = observation.get("domain") if isinstance(observation, dict) else None
        if isinstance(domain, dict) and domain.get("virtual_world"):
            domain["render_quality"] = render_quality
            domain["render_resolution"] = render_resolution
        if observation is not None:
            normalized_observation = Observation(**observation)
            normalized_observation.sample_id = (
                f"{new_run_id}-{index:03d}-{waypoint.waypoint_id}")
            assessment = engine.assess(normalized_observation, waypoint)
            item["assessment"] = to_jsonable(assessment)
            if scenario in {"successful", "synthetic_anomaly"} and assessment.severity.value == "NORMAL":
                item["work_order"] = None
            else:
                order = engine.create_work_order(
                    normalized_observation, waypoint, assessment,
                    site_config["site_id"], run_id=new_run_id,
                )
                order.created_at_utc = normalized_observation.timestamp_utc
                item["work_order"] = to_jsonable(order)

    work_orders = [
        item["work_order"]
        for item in rewritten_result.get("results", [])
        if isinstance(item, dict) and item.get("work_order") is not None
    ]
    payload["inspection_run.json"] = (
        json.dumps(rewritten_result, ensure_ascii=False, indent=2) + "\n"
    ).encode("utf-8")
    if scenario == "successful":
        payload["inspection_report.md"] = _render_successful_demo_report(
            rewritten_result,
            scene_detail_level=scene_detail_level,
        )
    elif scenario == "synthetic_anomaly":
        payload["inspection_report.md"] = _render_synthetic_anomaly_report(
            rewritten_result,
            scene_detail_level=scene_detail_level,
        )
    else:
        report = source_artifacts.get("inspection_report.md")
        if report is None:
            raise RuntimeError("Source artifact inspection_report.md is missing.")
        payload["inspection_report.md"] = report.replace(
            old_run_id.encode("utf-8"), new_run_id.encode("utf-8"))
    payload["work_orders.json"] = (
        json.dumps(work_orders, ensure_ascii=False, indent=2) + "\n"
    ).encode("utf-8")
    for name in ("scene_input.json", "trajectory.json"):
        content = source_artifacts.get(name)
        if content is None:
            raise RuntimeError(f"Source artifact {name} is missing.")
        payload[name] = content.replace(
            old_run_id.encode("utf-8"), new_run_id.encode("utf-8"))

    # The source result already carries the v24 scene references, but a newer
    # prebuilt render can add global camera files (for example a new MCC
    # interior still). Mirror VirtualWorldAdapter._attach_scene_artifacts so
    # those files remain scene evidence instead of being misclassified as
    # orphan sensor artifacts by result validation.
    first_observation = next(
        (
            item.get("observation")
            for item in rewritten_result.get("results", [])
            if isinstance(item, dict) and isinstance(item.get("observation"), dict)
        ),
        None,
    )
    if first_observation is not None:
        domain = first_observation.setdefault("domain", {})
        provenance = domain.setdefault("sensor_provenance", {
            "sensor_ids": [],
            "frame_id": "virtual_world/base_link/rgb_camera",
            "artifacts": [],
        })
        sensor_ids = provenance.setdefault("sensor_ids", [])
        if "virtual_scene" not in sensor_ids:
            sensor_ids.append("virtual_scene")
        references = provenance.setdefault("artifacts", [])
        # A source replay may contain Blender backup files or other scene
        # artifacts that are not carried into the new versioned scene bundle.
        # Drop stale virtual-scene references before adding the current bundle.
        references[:] = [
            item for item in references
            if not (
                isinstance(item, dict)
                and item.get("sensor_id") == "virtual_scene"
                and item.get("name") not in payload
            )
        ]
        existing_names = {
            item.get("name") for item in references
            if isinstance(item, dict)
        }
        waypoint_capture_names = {
            reference.get("name")
            for result_item in rewritten_result.get("results", [])
            if isinstance(result_item, dict)
            and isinstance(result_item.get("observation"), dict)
            for reference in result_item["observation"].get(
                "domain", {}
            ).get("sensor_provenance", {}).get("artifacts", [])
            if isinstance(reference, dict) and reference.get("sensor_id") == "rgb_camera"
        }
        timestamp = first_observation.get("timestamp_utc")
        scene_names = sorted(
            name for name in payload
            if name not in REQUIRED_FROM_SOURCE
            and name not in waypoint_capture_names
            and name not in existing_names
        )
        for name in scene_names:
            references.append({
                "name": name,
                "sensor_id": "virtual_scene",
                "media_type": _artifact_media_type(name),
                "timestamp_utc": timestamp,
            })
        domain["virtual_scene_artifacts"] = {
            "unit_scale": "1 Blender unit = 1 metre",
            "multi_camera": True,
            "artifact_names": sorted(
                name for name in payload
                if name not in REQUIRED_RESULT_ARTIFACTS
            ),
        }

    # Serialize after provenance augmentation so newly added global scene
    # files are present in the imported inspection result.
    payload["inspection_run.json"] = (
        json.dumps(rewritten_result, ensure_ascii=False, indent=2) + "\n"
    ).encode("utf-8")

    missing = REQUIRED_FROM_SOURCE - payload.keys()
    if missing:
        raise RuntimeError(f"Prebuilt scene import is missing artifacts: {sorted(missing)}")
    return payload


def import_prebuilt(
    *,
    demo_dir: Path,
    scene_dir: Path,
    source_db: Path,
    source_run_id: str = SOURCE_RUN_ID,
    run_id: str = DEFAULT_RUN_ID,
    site_config_path: Path,
    prebuilt_scene_name: str = "industrial-v23-full-768",
    scene_detail_level: str = "factory_environment_v23_high_granularity",
    idempotency_key: str = "local-demo-v23-prebuilt",
    scenario: str = "source",
    render_resolution: int = 768,
    render_quality: str = "ultra",
) -> bool:
    if scenario not in SCENARIOS:
        raise ValueError(f"Unsupported prebuilt import scenario: {scenario}")
    demo_dir.mkdir(parents=True, exist_ok=True)
    db_path = demo_dir / "inspection.db"
    artifact_dir = demo_dir / "artifacts"
    database_url = f"sqlite:///{db_path}"
    engine, session_factory = create_database(database_url, environment="local_demo")
    Base.metadata.create_all(engine)
    storage = LocalArtifactStorage(artifact_dir, max_bytes=200 * 1024 * 1024)
    storage.initialize()

    try:
        with session_factory() as session:
            existing = session.get(MissionRecord, run_id)
            if existing is not None:
                if existing.status != "SUCCEEDED":
                    raise RuntimeError(
                        f"Prebuilt mission {run_id} already exists with status {existing.status}.")
                return False

        source_result, source_artifacts = _read_source_artifacts(source_db, source_run_id)
        source_db_engine, source_session_factory = create_database(
            f"sqlite:///{source_db}", environment="local_demo")
        try:
            with source_session_factory() as source_session:
                source_mission = source_session.get(MissionRecord, source_run_id)
                if source_mission is None:
                    raise RuntimeError(f"Source mission {source_run_id} was not found.")
                frozen_manifest = json.loads(source_mission.manifest_json)
        finally:
            source_db_engine.dispose()

        site_config = json.loads(site_config_path.read_text(encoding="utf-8"))
        expected_config_hash = sha256_json(site_config)
        if frozen_manifest.get("config_sha256") != expected_config_hash:
            raise RuntimeError(
                "Source mission config hash does not match the current industrial site config.")

        frozen_manifest = _replace_run_id(
            frozen_manifest, source_run_id, run_id)
        if not isinstance(frozen_manifest, dict):
            raise RuntimeError("Frozen mission manifest is not a JSON object.")
        frozen_manifest["created_at_utc"] = _now_iso()
        frozen_manifest["render_backend"] = "blender"
        frozen_manifest["virtual_world"] = {
            **(frozen_manifest.get("virtual_world") or {}),
            "engine": "local_kinematic",
            "render_backend": "blender",
            "render_quality": render_quality,
            "render_resolution": render_resolution,
            "prebuilt_scene": prebuilt_scene_name,
            "scene_detail_level": scene_detail_level,
        }
        frozen_manifest["demo_scenario"] = scenario

        payload = _build_artifact_payload(
            scene_dir=scene_dir,
            source_artifacts=source_artifacts,
            result=source_result,
            site_config=site_config,
            old_run_id=source_run_id,
            new_run_id=run_id,
            scenario=scenario,
            scene_detail_level=scene_detail_level,
            render_resolution=render_resolution,
            render_quality=render_quality,
        )
        rewritten_result = json.loads(payload["inspection_run.json"].decode("utf-8"))
        source = rewritten_result["source"]
        descriptors = []
        for name, content in sorted(payload.items()):
            if isinstance(content, Path):
                digest = hashlib.sha256()
                size = 0
                with content.open("rb") as stream:
                    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                        digest.update(chunk)
                        size += len(chunk)
                descriptors.append({"name": name, "sha256": digest.hexdigest(), "size_bytes": size})
            else:
                descriptors.append({
                    "name": name,
                    "sha256": hashlib.sha256(content).hexdigest(),
                    "size_bytes": len(content),
                })
        result_manifest = {
            "schema_version": 1,
            "run_id": run_id,
            "source": source,
            "software_version": frozen_manifest["software_version"],
            "config_sha256": frozen_manifest["config_sha256"],
            "artifacts": descriptors,
        }
        request_payload = {
            "site_id": frozen_manifest["site_id"],
            "waypoint_ids": frozen_manifest["waypoint_ids"],
            "seed": frozen_manifest["seed"],
            "execution_backend": "offline",
            "render_backend": "blender",
            "render_quality": render_quality,
            "render_resolution": render_resolution,
        }
        now = datetime.now(timezone.utc)
        with session_factory() as session:
            mission = MissionRecord(
                run_id=run_id,
                site_id=frozen_manifest["site_id"],
                robot_id=frozen_manifest["robot_id"],
                execution_backend="offline",
                status="QUEUED",
                seed=frozen_manifest["seed"],
                manifest_json=canonical_json(frozen_manifest),
                request_hash=hashlib.sha256(canonical_json(request_payload).encode("utf-8")).hexdigest(),
                idempotency_key=idempotency_key,
                created_at=now,
                updated_at=now,
            )
            session.add(mission)
            session.flush()
            for name, content in sorted(payload.items()):
                if isinstance(content, Path):
                    descriptor = next(item for item in descriptors if item["name"] == name)
                    with content.open("rb") as stream:
                        store_artifact_file(
                            session, storage, run_id, name, stream,
                            descriptor["sha256"], descriptor["size_bytes"], source,
                        )
                else:
                    store_artifact_bytes(session, storage, run_id, name, content, source)
            _replay, result_hash = persist_inspection_result(
                session, mission, result_manifest, rewritten_result, storage)
            session.add(AuditEventRecord(
                event_id=uuid.uuid4().hex,
                actor="local-demo-prebuilt",
                actor_role="admin",
                event_type="MISSION_RESULT_IMPORTED",
                resource_type="mission",
                resource_id=run_id,
                payload_json=canonical_json({
                    "source": source,
                    "result_sha256": result_hash,
                    "artifact_count": len(descriptors),
                    "prebuilt_scene": prebuilt_scene_name,
                    "scenario": scenario,
                }),
                created_at=now,
            ))
            session.commit()
        return True
    finally:
        engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--demo-dir", type=Path, required=True)
    parser.add_argument("--scene-dir", type=Path, required=True)
    parser.add_argument("--source-db", type=Path, required=True)
    parser.add_argument("--site-config", type=Path, required=True)
    parser.add_argument("--source-run-id", default=SOURCE_RUN_ID)
    parser.add_argument("--run-id", default=DEFAULT_RUN_ID)
    parser.add_argument("--prebuilt-scene-name", default="industrial-v23-full-768")
    parser.add_argument("--scene-detail-level", default="factory_environment_v23_high_granularity")
    parser.add_argument("--idempotency-key", default="local-demo-v23-prebuilt")
    parser.add_argument("--scenario", choices=SCENARIOS, default="source")
    parser.add_argument("--render-resolution", type=int, default=768)
    parser.add_argument(
        "--render-quality", choices=("preview", "production", "ultra"), default="ultra",
    )
    args = parser.parse_args()
    if not args.scene_dir.is_dir():
        raise SystemExit(f"Scene directory does not exist: {args.scene_dir}")
    if not args.source_db.is_file():
        raise SystemExit(f"Source database does not exist: {args.source_db}")
    if not args.site_config.is_file():
        raise SystemExit(f"Site config does not exist: {args.site_config}")
    imported = import_prebuilt(
        demo_dir=args.demo_dir.resolve(),
        scene_dir=args.scene_dir.resolve(),
        source_db=args.source_db.resolve(),
        source_run_id=args.source_run_id,
        run_id=args.run_id,
        site_config_path=args.site_config.resolve(),
        prebuilt_scene_name=args.prebuilt_scene_name,
        scene_detail_level=args.scene_detail_level,
        idempotency_key=args.idempotency_key,
        scenario=args.scenario,
        render_resolution=args.render_resolution,
        render_quality=args.render_quality,
    )
    print(f"Prebuilt virtual-world mission {'imported' if imported else 'already present'}: {args.run_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
