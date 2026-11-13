#!/usr/bin/env python3
"""Validate the final V38 local demo bundle and both product branches."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sqlite3
import struct
import subprocess
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parents[1]
RUN_ID = os.getenv("LOCAL_DEMO_RUN_ID", "RUN-V38-HQ-SMOOTH-STREAM")
ANOMALY_RUN_ID = os.getenv("LOCAL_DEMO_ANOMALY_RUN_ID", "RUN-V38-SYNTHETIC-ANOMALY")
DEMO_DIR = Path(os.getenv("LOCAL_DEMO_DIR", str(ROOT / "outputs/local-demo-v38-smooth-stream")))
SCENE_DIR = Path(os.getenv(
    "LOCAL_DEMO_PREBUILT_SCENE_DIR", str(ROOT / "outputs/industrial-v38-smooth-stream"),
))
HEALTH_URL = os.getenv("LOCAL_DEMO_HEALTH_URL", "http://127.0.0.1:8017/healthz")


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


def probe_video(path: Path) -> dict[str, object]:
    result = subprocess.run(
        [
            "ffprobe", "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=codec_name,width,height,avg_frame_rate,nb_frames",
            "-show_entries", "format=duration", "-of", "json", str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)
    stream = (payload.get("streams") or [{}])[0]
    numerator, denominator = str(stream.get("avg_frame_rate") or "0/1").split("/", 1)
    return {
        "codec": stream.get("codec_name"),
        "width": int(stream.get("width") or 0),
        "height": int(stream.get("height") or 0),
        "fps": float(numerator) / float(denominator or 1),
        "frame_count": int(stream.get("nb_frames") or 0),
        "duration_s": float((payload.get("format") or {}).get("duration") or 0),
    }


def validate_anomaly_branch(connection: sqlite3.Connection) -> tuple[int, int]:
    row = connection.execute(
        "select status, manifest_json, result_json from missions where run_id = ?",
        (ANOMALY_RUN_ID,),
    ).fetchone()
    require(row is not None, f"anomaly mission is missing: {ANOMALY_RUN_ID}")
    status, manifest_json, result_json = row
    require(status == "SUCCEEDED", f"anomaly mission status is {status}")
    manifest = json.loads(manifest_json or "{}")
    require(manifest.get("demo_scenario") == "synthetic_anomaly", "anomaly scenario marker is missing")
    results = json.loads(result_json or "{}").get("results") or []
    require(len(results) == 10, f"expected 10 anomaly waypoint results, found {len(results)}")
    finding_count = sum(len((item.get("assessment") or {}).get("anomalies") or []) for item in results)
    order_count = connection.execute(
        "select count(*) from work_orders where run_id = ?", (ANOMALY_RUN_ID,),
    ).fetchone()[0]
    require(finding_count > 0, "anomaly branch has no rule findings")
    require(order_count > 0, "anomaly branch has no isolated work orders")
    return finding_count, order_count


def validate_continuous_stream(connection: sqlite3.Connection) -> tuple[int, int]:
    manifest = json.loads((SCENE_DIR / "continuous_video_manifest.json").read_text(encoding="utf-8"))
    require(manifest.get("stream_type") == "blender_rendered_continuous_video", "unexpected stream type")
    require(manifest.get("timeline") == "synchronized_route_time", "stream timeline is not route-synchronized")
    require(manifest.get("frame_count") == 48, "expected 48 source stream frames")
    require(manifest.get("route_frame_count") == 214, "expected 214 route frames")
    require(manifest.get("recommended_playback_speed") == 0.5, "expected 0.5x recommended playback")
    require(manifest.get("presentation_resolution") == {"width": 1280, "height": 720},
            "unexpected continuous presentation resolution")
    require(manifest.get("presentation_fps") == 60, "expected 60 FPS continuous presentation")
    streams = manifest.get("video_streams") or {}
    require(set(streams) == {"robot", "cctv"}, "robot and CCTV streams are not both declared")
    for kind, expected_name in (("robot", "robot_head_stream.mp4"), ("cctv", "warehouse_cctv_stream.mp4")):
        stream = streams[kind]
        require(stream.get("artifact") == expected_name, f"{kind} artifact name mismatch")
        path = SCENE_DIR / expected_name
        require(path.is_file() and path.stat().st_size > 0, f"{kind} MP4 is missing or empty")
        probe = probe_video(path)
        require(probe["codec"] == "h264", f"{kind} stream is not H.264")
        require((probe["width"], probe["height"]) == (1280, 720), f"{kind} stream dimensions are wrong")
        require(abs(float(probe["fps"]) - 60) < 0.1, f"{kind} stream is not 60 FPS")
        require(probe["frame_count"] >= 900, f"{kind} stream has too few encoded frames")
        require(float(probe["duration_s"]) > 15, f"{kind} stream duration is too short")
        artifact = connection.execute(
            "select storage_path, sha256, size_bytes from artifacts where run_id = ? and name = ?",
            (RUN_ID, expected_name),
        ).fetchone()
        require(artifact is not None, f"database artifact is missing: {expected_name}")
        stored_path, stored_hash, stored_size = artifact
        require(sha256_file(path) == stored_hash, f"scene hash mismatch: {expected_name}")
        require(path.stat().st_size == stored_size, f"scene size mismatch: {expected_name}")
        require(sha256_file(Path(stored_path)) == stored_hash, f"stored artifact differs: {expected_name}")
    return int(manifest["frame_count"]), int(manifest["route_frame_count"])


def main() -> int:
    require(DEMO_DIR.is_dir(), f"demo directory is missing: {DEMO_DIR}")
    require(SCENE_DIR.is_dir(), f"scene directory is missing: {SCENE_DIR}")
    with urlopen(HEALTH_URL, timeout=5) as response:
        health = json.loads(response.read().decode("utf-8"))
    require(health.get("status") == "ok", f"health check failed: {health}")

    # Reuse the established static-frame/GLB validator for the successful branch.
    os.environ.update({
        "LOCAL_DEMO_RUN_ID": RUN_ID,
        "LOCAL_DEMO_DIR": str(DEMO_DIR),
        "LOCAL_DEMO_PREBUILT_SCENE_DIR": str(SCENE_DIR),
        "LOCAL_DEMO_HEALTH_URL": HEALTH_URL,
    })
    sys_path = str(Path(__file__).resolve().parent)
    import sys
    if sys_path not in sys.path:
        sys.path.insert(0, sys_path)
    import validate_local_demo_v34 as baseline

    baseline.main()
    with sqlite3.connect(DEMO_DIR / "inspection.db") as connection:
        finding_count, order_count = validate_anomaly_branch(connection)
        stream_frames, route_frames = validate_continuous_stream(connection)

    print("V38_LOCAL_DEMO_VALIDATION=PASS")
    print(f"success_run={RUN_ID} anomaly_run={ANOMALY_RUN_ID}")
    print(f"continuous_streams=robot+cctv frames={stream_frames} route_frames={route_frames} fps=60")
    print(f"synthetic_findings={finding_count} isolated_work_orders={order_count}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError, sqlite3.Error, subprocess.SubprocessError) as exc:
        raise SystemExit(f"V38_LOCAL_DEMO_VALIDATION=FAIL: {exc}") from exc
