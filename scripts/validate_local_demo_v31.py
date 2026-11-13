#!/usr/bin/env python3
"""Validate the running v31 local product demo and its immutable scene bundle."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sqlite3
import struct
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parents[1]
RUN_ID = os.getenv("LOCAL_DEMO_RUN_ID", "RUN-V31-FINAL-PRODUCT-DEMO-SUCCESS")
DEMO_DIR = Path(os.getenv("LOCAL_DEMO_DIR", str(ROOT / "outputs/local-demo-v31-final")))
SCENE_DIR = Path(os.getenv("LOCAL_DEMO_PREBUILT_SCENE_DIR", str(ROOT / "outputs/industrial-v31-final-1280")))
HEALTH_URL = os.getenv("LOCAL_DEMO_HEALTH_URL", "http://127.0.0.1:8011/healthz")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def png_size(path: Path) -> tuple[int, int]:
    header = path.read_bytes()[:24]
    require(header[:8] == b"\x89PNG\r\n\x1a\n", f"{path.name} is not a PNG")
    return struct.unpack(">II", header[16:24])


def glb_node_names(path: Path) -> list[str]:
    data = path.read_bytes()
    require(data[:4] == b"glTF", f"{path.name} is not a GLB")
    json_length = struct.unpack_from("<I", data, 12)[0]
    payload = data[20:20 + json_length].rstrip(b" \x00")
    document = json.loads(payload.decode("utf-8"))
    return [str(node["name"]) for node in document.get("nodes", []) if node.get("name")]


def main() -> int:
    require(DEMO_DIR.is_dir(), f"demo directory is missing: {DEMO_DIR}")
    require(SCENE_DIR.is_dir(), f"scene directory is missing: {SCENE_DIR}")

    with urlopen(HEALTH_URL, timeout=5) as response:
        health = json.loads(response.read().decode("utf-8"))
    require(health.get("status") == "ok", f"health check failed: {health}")

    database = DEMO_DIR / "inspection.db"
    require(database.is_file(), f"demo database is missing: {database}")
    with sqlite3.connect(database) as connection:
        mission_row = connection.execute(
            "select status, result_json from missions where run_id = ?",
            (RUN_ID,),
        ).fetchone()
        require(mission_row is not None, f"mission is missing: {RUN_ID}")
        status, result_json = mission_row
        require(status == "SUCCEEDED", f"mission status is {status}, expected SUCCEEDED")
        result = json.loads(result_json or "{}")
        results = result.get("results") or []
        require(len(results) == 10, f"expected 10 waypoint results, found {len(results)}")
        require(
            all(item.get("navigation_status") == "SUCCEEDED" for item in results),
            "one or more waypoint navigation results did not succeed",
        )
        require(
            all(item.get("inspection_status") == "COMPLETED" for item in results),
            "one or more waypoint inspections did not complete",
        )
        require(
            all((item.get("assessment") or {}).get("severity") == "NORMAL" for item in results),
            "one or more waypoint assessments are not NORMAL",
        )
        work_order_count = connection.execute(
            "select count(*) from work_orders where run_id = ?", (RUN_ID,)
        ).fetchone()[0]
        require(work_order_count == 0, f"expected 0 work orders, found {work_order_count}")
        artifact_row = connection.execute(
            "select storage_path, sha256, size_bytes from artifacts "
            "where run_id = ? and name = 'factory_scene.glb'",
            (RUN_ID,),
        ).fetchone()
        require(artifact_row is not None, "factory_scene.glb artifact is missing from the demo database")

    glb_path = SCENE_DIR / "factory_scene.glb"
    require(glb_path.is_file(), f"scene GLB is missing: {glb_path}")
    stored_path, stored_hash, stored_size = artifact_row
    require(Path(stored_path).is_file(), f"stored GLB is missing: {stored_path}")
    scene_hash = sha256_file(glb_path)
    require(scene_hash == stored_hash, "scene GLB hash does not match the API artifact record")
    require(glb_path.stat().st_size == stored_size, "scene GLB size does not match the API artifact record")
    require(sha256_file(Path(stored_path)) == scene_hash, "stored API GLB differs from the scene bundle")

    camera_manifest = json.loads((SCENE_DIR / "factory_camera_manifest.json").read_text(encoding="utf-8"))
    require(len(camera_manifest.get("cameras", [])) == 64, "expected 64 camera artifacts")

    stream_manifest = json.loads((SCENE_DIR / "synchronized_video_manifest.json").read_text(encoding="utf-8"))
    require(stream_manifest.get("frame_count") == 48, "expected 48 synchronized stream frames")
    require(stream_manifest.get("recommended_playback_speed") == 0.5, "expected 0.5x recommended playback")
    require(stream_manifest.get("resolution") == {"width": 512, "height": 288}, "unexpected stream resolution")

    expected_sizes = {
        "factory_overview.png": (1280, 720),
        "factory_orbit_01.png": (768, 480),
        "robot_rgb_stream__F0001.png": (512, 288),
        "warehouse_cctv_stream__F0001.png": (512, 288),
    }
    for name, expected in expected_sizes.items():
        actual = png_size(SCENE_DIR / name)
        require(actual == expected, f"{name} has size {actual}, expected {expected}")

    names = glb_node_names(glb_path)
    require(any(name.startswith("RoofTruss") for name in names), "GLB has no preserved roof truss nodes")
    require(any(name.startswith("RoofPurlin") for name in names), "GLB has no preserved roof purlin nodes")
    require("North_RingBeam" in names and "East_RingBeam" in names, "GLB is missing preserved ring beams")

    print("V31_LOCAL_DEMO_VALIDATION=PASS")
    print(f"run_id={RUN_ID} status={status} waypoints={len(results)} work_orders={work_order_count}")
    print(f"cameras={len(camera_manifest['cameras'])} stream_frames={stream_manifest['frame_count']} glb_sha256={scene_hash}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError, sqlite3.Error) as exc:
        raise SystemExit(f"V31_LOCAL_DEMO_VALIDATION=FAIL: {exc}") from exc
