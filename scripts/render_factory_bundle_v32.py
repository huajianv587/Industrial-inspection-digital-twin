#!/usr/bin/env python3
"""Render a complete, auditable camera bundle from a saved Blender scene."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import struct
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from blender_sim.render_factory import (  # noqa: E402
    _configure_render_effects,
    _configure_render_quality,
    _render_synchronized_streams,
)


def arguments() -> argparse.Namespace:
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-scene-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--resolution", type=int, default=768)
    parser.add_argument("--quality", choices=("production", "ultra"), default="production")
    parser.add_argument("--stream-quality", choices=("preview", "production"), default="preview")
    parser.add_argument("--stream-frames", type=int, default=48)
    parser.add_argument("--stream-resolution", type=int, default=512)
    parser.add_argument("--camera-filter", action="append", default=[])
    parser.add_argument("--skip-streams", action="store_true")
    return parser.parse_args(argv)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def png_dimensions(path: Path) -> tuple[int, int]:
    with path.open("rb") as stream:
        header = stream.read(24)
    if len(header) != 24 or header[:8] != b"\x89PNG\r\n\x1a\n":
        raise RuntimeError(f"Invalid PNG output: {path}")
    return struct.unpack(">II", header[16:24])


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def camera_filename(camera, scene_data: dict) -> str:
    role = str(camera.get("camera_role", ""))
    waypoint_id = str(camera.get("sync_waypoint_id", ""))
    if role == "robot_first_person":
        return "factory_robot_first_person.png"
    if role == "robot_rgb":
        return f"virtual_world__{waypoint_id}__rgb_camera.png"
    if role == "warehouse_cctv":
        return f"factory_cctv__{waypoint_id}.png"

    name = camera.name.removeprefix("CAM_")
    if name.startswith("DETAIL_"):
        index = int(name.rsplit("_", 1)[1]) - 1
        waypoints = scene_data.get("waypoints", [])
        if not 0 <= index < len(waypoints):
            raise RuntimeError(f"Camera does not map to a waypoint: {camera.name}")
        return f"factory_detail_{waypoints[index]['waypoint_id'].lower()}.png"
    if name.startswith("HERO_"):
        return f"factory_hero_{name.removeprefix('HERO_').lower()}.png"
    if name.startswith("ORBIT_"):
        return f"factory_orbit_{name.removeprefix('ORBIT_')}.png"
    return f"factory_{name.lower()}.png"


def atomic_json(path: Path, document: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
    )
    temporary.replace(path)


def main() -> int:
    args = arguments()
    source_dir = args.source_scene_dir.resolve()
    output_dir = args.output_dir.resolve()
    source_blend = source_dir / "factory_scene.blend"
    source_scene_input = source_dir / "scene_input.json"
    source_manifest = source_dir / "factory_camera_manifest.json"
    for required in (source_blend, source_scene_input, source_manifest):
        if not required.is_file():
            raise RuntimeError(f"Required source artifact is missing: {required}")

    output_dir.mkdir(parents=True, exist_ok=True)
    if output_dir == source_dir:
        raise RuntimeError("The v32 output directory must not be the source scene directory.")
    for name in ("factory_scene.glb", "scene_input.json"):
        source = source_dir / name
        if source.is_file() and not (output_dir / name).exists():
            shutil.copy2(source, output_dir / name)
    shutil.copy2(source_manifest, output_dir / "factory_camera_manifest.json")

    scene_data = json.loads(source_scene_input.read_text(encoding="utf-8"))
    manifest = json.loads(source_manifest.read_text(encoding="utf-8"))
    camera_manifest = output_dir / "factory_camera_manifest.json"
    manifest["render_quality"] = args.quality
    manifest["render_resolution"] = {
        "width": args.resolution,
        "height": max(480, int(args.resolution * 9 / 16)),
    }
    manifest["rendered_cameras"] = []
    camera_metadata = manifest.setdefault("camera_metadata", {})
    for metadata in camera_metadata.values():
        metadata["rendered"] = False
        for key in ("sha256", "size_bytes", "width", "height", "rendered_at_utc"):
            metadata.pop(key, None)
    import bpy

    bpy.ops.wm.open_mainfile(filepath=str(source_blend))
    scene = bpy.context.scene
    scene.render.resolution_x = args.resolution
    scene.render.resolution_y = max(480, int(args.resolution * 9 / 16))
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.image_settings.compression = 15
    scene.render.use_persistent_data = True
    settings = _configure_render_quality(scene, args.quality)
    _configure_render_effects(scene, args.quality)

    cameras = {}
    for camera in bpy.data.objects:
        if camera.type != "CAMERA":
            continue
        filename = camera_filename(camera, scene_data)
        if filename in cameras:
            raise RuntimeError(f"Duplicate camera artifact mapping: {filename}")
        cameras[filename] = camera
    expected = set(manifest.get("cameras", []))
    actual = set(cameras)
    if actual != expected:
        raise RuntimeError(
            f"Camera bundle mismatch; missing={sorted(expected - actual)}, "
            f"unexpected={sorted(actual - expected)}"
        )

    filters = tuple(token.strip() for value in args.camera_filter
                    for token in value.split(",") if token.strip())
    selected = [name for name in sorted(cameras)
                if not filters or any(token in name for token in filters)]
    if not selected:
        raise RuntimeError("Camera filter matched no camera artifacts.")

    scene_detail_names = {name for name in selected
                          if name.startswith("factory_detail_")}
    for filename in selected:
        camera = cameras[filename]
        metadata = camera_metadata.setdefault(filename, {})
        role = str(camera.get("camera_role", metadata.get("camera_role", "scene_camera")))
        metadata.update({
            "camera_role": role,
            "render_frame": int(camera.get("render_frame", metadata.get("render_frame", 1))),
            "rendered": False,
        })
        if "sync_waypoint_id" in camera:
            metadata["sync_waypoint_id"] = str(camera["sync_waypoint_id"])
            metadata["sync_trajectory_index"] = int(camera["sync_trajectory_index"])

        # Inspection evidence should stay sharp across the complete target plane.
        if role in {"robot_rgb", "robot_first_person", "warehouse_cctv"} \
                or filename in scene_detail_names:
            camera.data.dof.use_dof = False
        elif filename == "factory_hero_gauge_macro.png":
            camera.data.dof.aperture_fstop = 22.0

        path = output_dir / filename
        target_dimensions = (
            args.resolution, max(480, int(args.resolution * 9 / 16)),
        )
        if path.is_file():
            try:
                existing_dimensions = png_dimensions(path)
            except RuntimeError:
                existing_dimensions = None
        else:
            existing_dimensions = None
        if existing_dimensions != target_dimensions:
            scene.camera = camera
            scene.frame_set(metadata["render_frame"])
            scene.render.filepath = str(path)
            bpy.ops.render.render(write_still=True)
        width, height = png_dimensions(path)
        if (width, height) != target_dimensions:
            raise RuntimeError(f"Unexpected dimensions for {filename}: {width}x{height}")
        record = {
            "sha256": sha256(path),
            "size_bytes": path.stat().st_size,
            "width": width,
            "height": height,
            "render_frame": metadata["render_frame"],
            "rendered_at_utc": now_utc(),
        }
        metadata.update({"rendered": True, **record})
        manifest["rendered_cameras"] = sorted(
            name for name in expected
            if camera_metadata.get(name, {}).get("rendered") is True
            and (output_dir / name).is_file()
        )
        manifest["camera_artifacts"] = camera_metadata
        manifest["render_settings"] = settings
        manifest["render_engine"] = scene.render.engine
        manifest["renderer_version"] = bpy.app.version_string
        manifest["source_scene_sha256"] = sha256(source_blend)
        manifest["rendered_locally"] = True
        manifest["v32_inspection_focus"] = "depth_of_field_disabled_for_sensor_and_detail_views"
        atomic_json(camera_manifest, manifest)
        print(f"V32_CAMERA_RENDERED={filename} size={width}x{height}", flush=True)

    # Persist the camera-profile settings before switching to the cheaper stream profile.
    scene.frame_set(1)
    scene.camera = cameras["factory_overview.png"]
    bpy.ops.wm.save_as_mainfile(filepath=str(output_dir / "factory_scene.blend"))

    stream_manifest = {}
    if not args.skip_streams and not filters:
        stream_settings = _configure_render_quality(scene, args.stream_quality)
        stream_manifest = _render_synchronized_streams(
            bpy, scene, output_dir, scene_data.get("trajectory", []),
            quality=args.stream_quality,
            frame_count=args.stream_frames,
            stream_resolution=args.stream_resolution,
        )
        if len(stream_manifest.get("frames", [])) != args.stream_frames:
            raise RuntimeError("Synchronized stream did not render the requested frame count.")
    else:
        stream_settings = {}

    rendered_names = sorted(
        name for name in expected if camera_metadata.get(name, {}).get("rendered") is True
    )
    manifest["rendered_cameras"] = rendered_names
    manifest["complete_camera_set"] = len(rendered_names) == len(expected)
    manifest["camera_count"] = len(expected)
    manifest["render_settings"] = settings
    manifest["render_engine"] = scene.render.engine
    manifest["renderer_version"] = bpy.app.version_string
    atomic_json(camera_manifest, manifest)

    stream_hashes = {}
    if stream_manifest:
        for frame in stream_manifest["frames"]:
            for key in ("robot_artifact", "cctv_artifact"):
                filename = frame[key]
                path = output_dir / filename
                width, height = png_dimensions(path)
                expected_dimensions = (
                    args.stream_resolution,
                    max(144, int(args.stream_resolution * 9 / 16)),
                )
                if (width, height) != expected_dimensions:
                    raise RuntimeError(f"Unexpected dimensions for {filename}: {width}x{height}")
                stream_hashes[filename] = {
                    "sha256": sha256(path),
                    "size_bytes": path.stat().st_size,
                    "width": width,
                    "height": height,
                    "trajectory_index": frame["trajectory_index"],
                    "render_frame": frame["render_frame"],
                }

    release = {
        "schema_version": 1,
        "release": "industrial-v32-camera-complete",
        "created_at_utc": now_utc(),
        "source_bundle": "industrial-v31-final-1280",
        "source_scene_sha256": sha256(source_blend),
        "source_glb_sha256": sha256(output_dir / "factory_scene.glb"),
        "blender_version": bpy.app.version_string,
        "render_engine": scene.render.engine,
        "render_quality": args.quality,
        "stream_render_quality": args.stream_quality,
        "camera_resolution": manifest["render_resolution"],
        "camera_count": len(expected),
        "rendered_camera_count": len(rendered_names),
        "camera_artifacts": {
            name: {
                "sha256": camera_metadata[name]["sha256"],
                "size_bytes": camera_metadata[name]["size_bytes"],
                "width": camera_metadata[name]["width"],
                "height": camera_metadata[name]["height"],
                "render_frame": camera_metadata[name]["render_frame"],
            }
            for name in rendered_names
        },
        "stream_frame_count": len(stream_manifest.get("frames", [])),
        "stream_render_settings": stream_settings,
        "stream_artifacts": stream_hashes,
        "synchronized_waypoint_captures": manifest.get("synchronized_captures", []),
        "limitations": [
            "This is a local synthetic Blender scene, not a real facility scan.",
            "The robot route and all sensor images are simulated, not live hardware data.",
        ],
    }
    atomic_json(output_dir / "v32_release_manifest.json", release)
    print(
        f"V32_BUNDLE_RENDERED cameras={len(rendered_names)}/{len(expected)} "
        f"streams={len(stream_hashes)} output={output_dir}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        raise SystemExit(f"V32_RENDER_FAILED: {exc}") from exc
