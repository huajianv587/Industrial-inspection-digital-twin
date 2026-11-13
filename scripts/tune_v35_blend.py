#!/usr/bin/env python3
"""Apply small post-build v35 material corrections to an existing blend."""

from __future__ import annotations

import argparse
import bpy


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(__import__("sys").argv[__import__("sys").argv.index("--") + 1:])

    bpy.ops.wm.open_mainfile(filepath=args.input)
    for key, alpha, roughness in (
        ("GaugeGlass", 0.20, 0.08),
        ("V35AntiGlareGlass", 0.10, 0.045),
    ):
        material = bpy.data.materials.get(key)
        if material is None or not getattr(material, "use_nodes", False):
            continue
        shader = material.node_tree.nodes.get("Principled BSDF")
        if shader is None:
            continue
        if shader.inputs.get("Alpha") is not None:
            shader.inputs["Alpha"].default_value = alpha
        if shader.inputs.get("Roughness") is not None:
            shader.inputs["Roughness"].default_value = roughness
    bpy.ops.wm.save_as_mainfile(filepath=args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
