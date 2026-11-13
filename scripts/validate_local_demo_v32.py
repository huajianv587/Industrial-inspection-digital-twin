#!/usr/bin/env python3
"""Validate the v32 demo, complete camera bundle, and synchronized frames."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sqlite3
import struct
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parents[1]
RUN_ID = os.getenv("LOCAL_DEMO_RUN_ID", "RUN-V32-FINAL-CAMERA-COMPLETE-SUCCESS")
DEMO_DIR = Path(os.getenv("LOCAL_DEMO_DIR", str(ROOT / "outputs/local-demo-v32-final")))
SCENE_DIR = Path(os.getenv(
    "LOCAL_DEMO_PREBUILT_SCENE_DIR", str(ROOT / "outputs/industrial-v32-release-1280"),
))
HEALTH_URL = os.getenv("LOCAL_DEMO_HEALTH_URL", "http://127.0.0.1:8012/healthz")


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
    with path.open("rb") as stream:
        header = stream.read(24)
    require(header[:8] == b"\x89PNG\r\n\x1a\n", f"{path.name} is not a PNG")
    return struct.unpack(">II", header[16:24])


def main() -> int:
    require(DEMO_DIR.is_dir(), f"demo directory is missing: {DEMO_DIR}")
    require(SCENE_DIR.is_dir(), f"scene directory is missing: {SCENE_DIR}")
    with urlopen(HEALTH_URL, timeout=5) as response:
        health = json.loads(response.read().decode("utf-8"))
    require(health.get("status") == "ok", f"health check failed: {health}")

    with sqlite3.connect(DEMO_DIR / "inspection.db") as connection:
        mission_row = connection.execute(
            "select status, result_json from missions where run_id = ?", (RUN_ID,),
        ).fetchone()
        require(mission_row is not None, f"mission is missing: {RUN_ID}")
        status, result_json = mission_row
        require(status == "SUCCEEDED", f"mission status is {status}, expected SUCCEEDED")
        results = (json.loads(result_json or "{}").get("results") or [])
        require(len(results) == 10, f"expected 10 waypoint results, found {len(results)}")
        require(all(item.get("navigation_status") == "SUCCEEDED" for item in results),
                "one or more waypoint navigation results did not succeed")
        require(all(item.get("inspection_status") == "COMPLETED" for item in results),
                "one or more waypoint inspections did not complete")
        require(all((item.get("assessment") or {}).get("severity") == "NORMAL"
                    for item in results), "one or more waypoint assessments are not NORMAL")
        work_orders = connection.execute(
            "select count(*) from work_orders where run_id = ?", (RUN_ID,),
        ).fetchone()[0]
        require(work_orders == 0, f"expected 0 work orders, found {work_orders}")
        artifact_row = connection.execute(
            "select storage_path, sha256, size_bytes from artifacts "
            "where run_id = ? and name = 'factory_scene.glb'", (RUN_ID,),
        ).fetchone()
        require(artifact_row is not None, "factory_scene.glb database artifact is missing")

    camera_manifest = json.loads(
        (SCENE_DIR / "factory_camera_manifest.json").read_text(encoding="utf-8"),
    )
    release = json.loads((SCENE_DIR / "v32_release_manifest.json").read_text(encoding="utf-8"))
    expected_cameras = set(camera_manifest.get("cameras", []))
    rendered_cameras = set(camera_manifest.get("rendered_cameras", []))
    require(len(expected_cameras) == 64, f"expected 64 cameras, found {len(expected_cameras)}")
    require(rendered_cameras == expected_cameras, "not every camera has a fresh v32 render")
    require(camera_manifest.get("complete_camera_set") is True, "camera set is not marked complete")
    require(camera_manifest.get("render_resolution") == {"width": 768, "height": 480},
            "camera render resolution is not 768x480")
    require(release.get("rendered_camera_count") == 64, "release manifest camera count mismatch")

    for name in sorted(expected_cameras):
        path = SCENE_DIR / name
        require(path.is_file(), f"camera render is missing: {name}")
        require(png_size(path) == (768, 480), f"{name} is not 768x480")
        record = release["camera_artifacts"].get(name)
        require(record is not None, f"camera hash is missing from release manifest: {name}")
        require(sha256_file(path) == record["sha256"], f"camera hash mismatch: {name}")
        require(path.stat().st_size == record["size_bytes"], f"camera size mismatch: {name}")

    captures = camera_manifest.get("synchronized_captures", [])
    require(len(captures) == 10, f"expected 10 synchronized waypoint pairs, found {len(captures)}")
    for capture in captures:
        require(capture.get("same_route_frame") is True, "camera pair has mismatched route frames")
        for key in ("robot_rgb_artifact", "warehouse_cctv_artifact"):
            name = capture[key]
            metadata = camera_manifest["camera_artifacts"].get(name, {})
            require(metadata.get("rendered") is True, f"synchronized still was not rendered: {name}")
            require(metadata.get("render_frame") == capture.get("render_frame"),
                    f"synchronized still frame mismatch: {name}")

    stream = json.loads((SCENE_DIR / "synchronized_video_manifest.json").read_text(encoding="utf-8"))
    require(stream.get("frame_count") == 48, "expected 48 synchronized stream frames")
    require(stream.get("recommended_playback_speed") == 0.5, "expected 0.5x playback speed")
    require(stream.get("resolution") == {"width": 512, "height": 288},
            "unexpected synchronized stream resolution")
    require(len(release.get("stream_artifacts", {})) == 96,
            "expected 96 hashed robot/CCTV stream images")
    for frame in stream.get("frames", []):
        require(frame.get("same_route_frame") is True, "stream frame pair is not synchronized")
        for key in ("robot_artifact", "cctv_artifact"):
            name = frame[key]
            record = release["stream_artifacts"].get(name)
            require(record is not None, f"stream hash is missing: {name}")
            require(png_size(SCENE_DIR / name) == (512, 288), f"{name} is not 512x288")
            require(sha256_file(SCENE_DIR / name) == record["sha256"],
                    f"stream hash mismatch: {name}")
            require(record.get("trajectory_index") == frame.get("trajectory_index"),
                    f"stream route index mismatch: {name}")

    glb_path = SCENE_DIR / "factory_scene.glb"
    stored_path, stored_hash, stored_size = artifact_row
    require(sha256_file(glb_path) == stored_hash, "scene GLB hash does not match API artifact")
    require(glb_path.stat().st_size == stored_size, "scene GLB size does not match API artifact")
    require(sha256_file(Path(stored_path)) == stored_hash, "stored API GLB differs from scene bundle")

    print("V32_LOCAL_DEMO_VALIDATION=PASS")
    print(f"run_id={RUN_ID} status={status} waypoints={len(results)} work_orders={work_orders}")
    print("camera_renders=64/64 resolution=768x480 synchronized_stills=10/10")
    print("stream_frames=48 robot_cctv_images=96 resolution=512x288 playback=0.5x")
    print(f"glb_sha256={stored_hash}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError, sqlite3.Error) as exc:
        raise SystemExit(f"V32_LOCAL_DEMO_VALIDATION=FAIL: {exc}") from exc
