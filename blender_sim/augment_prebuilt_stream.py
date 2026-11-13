#!/usr/bin/env python3
"""Augment an existing rendered factory with v28 geometry and a light stream."""

from __future__ import annotations

import json
from pathlib import Path
import sys


def main() -> int:
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
    if len(argv) != 3:
        raise SystemExit("usage: augment_prebuilt_stream.py -- <blend> <scene_input> <output_dir>")
    blend_path, scene_input_path, output_dir = map(Path, argv)
    import bpy

    script_dir = Path(__file__).resolve().parent
    if str(script_dir) not in sys.path:
        sys.path.insert(0, str(script_dir))
    import render_factory

    bpy.ops.wm.open_mainfile(filepath=str(blend_path))
    scene_data = json.loads(scene_input_path.read_text(encoding="utf-8"))
    material_names = {
        "fastener": "FastenerSteel",
        "wall_joint": "WallPanelJoint",
        "label_plate": "LabelPlate",
        "conduit": "ElectricalConduit",
        "floor_joint": "FloorJoint",
    }
    materials = {
        key: bpy.data.materials.get(name)
        for key, name in material_names.items()
    }
    missing = [key for key, value in materials.items() if value is None]
    if missing:
        raise RuntimeError(f"v28 materials are missing from the prebuilt scene: {missing}")

    bounds = render_factory._bounds(scene_data)
    render_factory._add_v28_micro_geometry_layer(
        bpy, scene_data, bounds, materials,
    )
    scene = bpy.context.scene
    render_factory._configure_render_quality(scene, "production")
    render_factory._configure_render_effects(scene, "production")
    render_factory._render_synchronized_streams(
        bpy, scene, output_dir, scene_data.get("trajectory", []),
        quality="production", frame_count=48, stream_resolution=512,
    )

    scene.frame_set(1)
    overview = bpy.data.objects.get("CAM_OVERVIEW")
    if overview is not None:
        scene.camera = overview
    bpy.ops.wm.save_as_mainfile(filepath=str(output_dir / "factory_scene.blend"))
    glb_path = output_dir / "factory_scene.glb"
    try:
        bpy.ops.export_scene.gltf(filepath=str(glb_path), export_format="GLB", export_apply=True)
    except Exception as exc:
        print(f"GLB export unavailable: {type(exc).__name__}: {exc}", file=sys.stderr)
        glb_path.unlink(missing_ok=True)

    manifest_path = output_dir / "factory_camera_manifest.json"
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["scene_detail_level"] = "factory_environment_v28_micro_geometry_stream_ready"
        manifest["stream_manifest"] = "synchronized_video_manifest.json"
        layers = list(manifest.get("environment_layers", []))
        for layer in (
            "v28 cladding seams, captive fasteners and wall panel anchors",
            "v28 field service plates, cable glands and strain-relief tails",
            "v28 floor joint inserts and waypoint calibration witness plates",
            "route-indexed sampled robot RGB and fixed CCTV image stream",
        ):
            if layer not in layers:
                layers.append(layer)
        manifest["environment_layers"] = layers
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
