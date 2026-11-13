#!/usr/bin/env python3
"""Render a higher-fidelity continuous Blender stream from an existing scene.

This keeps the validated scene bundle immutable and only regenerates the two
browser stream cameras. The source PNGs remain the auditable evidence; the MP4
is a presentation stream for the local synthetic replay.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
BLENDER_SIM = ROOT / "blender_sim"
if str(BLENDER_SIM) not in sys.path:
    sys.path.insert(0, str(BLENDER_SIM))


def _args() -> argparse.Namespace:
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
    parser = argparse.ArgumentParser()
    parser.add_argument("--scene-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--frame-count", type=int, default=120)
    parser.add_argument("--stream-resolution", type=int, default=1280)
    parser.add_argument("--quality", choices=("production", "ultra"), default="ultra")
    parser.add_argument("--duration", type=float, default=17.28)
    return parser.parse_args(argv)


def main() -> int:
    args = _args()
    try:
        import bpy
    except ImportError as exc:
        raise SystemExit("This script must be launched by Blender's Python runtime.") from exc

    scene_dir = args.scene_dir.resolve()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    scene_input_path = scene_dir / "scene_input.json"
    blend_path = scene_dir / "factory_scene.blend"
    if not scene_input_path.is_file() or not blend_path.is_file():
        raise SystemExit(f"scene bundle is incomplete: {scene_dir}")
    if args.frame_count < 2:
        raise SystemExit("--frame-count must be at least 2")
    if args.stream_resolution < 640:
        raise SystemExit("--stream-resolution must be at least 640 for HQ output")

    import render_factory

    bpy.ops.wm.open_mainfile(filepath=str(blend_path))
    scene = bpy.context.scene
    available_engines = {
        item.identifier
        for item in bpy.types.RenderSettings.bl_rna.properties["engine"].enum_items
    }
    if "BLENDER_EEVEE_NEXT" in available_engines:
        scene.render.engine = "BLENDER_EEVEE_NEXT"
    elif "BLENDER_EEVEE" in available_engines:
        scene.render.engine = "BLENDER_EEVEE"
    render_factory._configure_render_quality(scene, args.quality)
    render_factory._configure_render_effects(scene, args.quality)
    scene.render.resolution_percentage = 100
    scene.render.use_persistent_data = True
    scene.render.image_settings.file_format = "PNG"
    try:
        scene.view_settings.look = "AgX - Medium High Contrast"
    except TypeError:
        pass

    scene_input = json.loads(scene_input_path.read_text(encoding="utf-8"))
    trajectory = scene_input.get("trajectory") or []
    if not trajectory:
        raise SystemExit("scene_input.json does not contain a trajectory")
    frame_duration = max(0.001, float(args.duration) / float(args.frame_count))
    manifest = render_factory._render_synchronized_streams(
        bpy,
        scene,
        output_dir,
        trajectory,
        quality=args.quality,
        frame_count=args.frame_count,
        stream_resolution=args.stream_resolution,
        frame_duration_s=frame_duration,
    )
    if not manifest or len(manifest.get("frames", [])) < 2:
        raise SystemExit("continuous stream render produced no usable frames")
    manifest["stream_profile"] = "HQ_CONTINUOUS"
    manifest["render_engine"] = scene.render.engine
    manifest["render_quality"] = args.quality
    manifest["source_scene"] = str(blend_path)
    manifest["source_frame_count"] = len(trajectory)
    (output_dir / "hq_stream_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        "HQ_STREAM_RENDER=PASS "
        f"frames={len(manifest['frames'])} "
        f"resolution={manifest['resolution']['width']}x{manifest['resolution']['height']} "
        f"frame_duration_s={frame_duration:.6f} "
        f"engine={scene.render.engine}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
