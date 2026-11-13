#!/usr/bin/env python3
"""Export a portable GLB from a saved v35 Blender scene."""

from __future__ import annotations

import argparse
import sys

import bpy

ROOT = __import__("pathlib").Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from blender_sim.render_factory import _join_static_meshes_for_glb, _prepare_glb_export_materials  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    argv = __import__("sys").argv
    args = parser.parse_args(argv[argv.index("--") + 1:])
    bpy.ops.wm.open_mainfile(filepath=args.input)
    flattened = _prepare_glb_export_materials(bpy)
    merged = _join_static_meshes_for_glb(bpy)
    bpy.ops.export_scene.gltf(filepath=args.output, export_format="GLB", export_apply=True)
    print(f"V35_GLB_EXPORTED materials={flattened} merged_objects={merged}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
