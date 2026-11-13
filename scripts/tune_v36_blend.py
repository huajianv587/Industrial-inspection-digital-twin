#!/usr/bin/env python3
"""Add a precision inspection-detail pass to a saved v35 Blender scene."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys

import bpy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from blender_sim.render_factory import (  # noqa: E402
    _box,
    _cylinder,
    _material,
    _pipe_between,
    _text,
    _torus,
)


def _args() -> argparse.Namespace:
    argv = sys.argv[sys.argv.index("--") + 1:]
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--scene-input", required=True, type=Path)
    return parser.parse_args(argv)


def _precision_materials():
    return {
        "plate": _material(
            bpy, "V36_SerialPlate", (0.34, 0.37, 0.36, 1),
            metallic=0.72, roughness=0.30, texture_scale=34, bump_distance=0.012,
        ),
        "ink": _material(
            bpy, "V36_EngravedInk", (0.025, 0.031, 0.029, 1),
            metallic=0.05, roughness=0.58,
        ),
        "white": _material(
            bpy, "V36_InspectionWhite", (0.82, 0.84, 0.80, 1),
            metallic=0.05, roughness=0.46, texture_scale=22, bump_distance=0.006,
        ),
        "black": _material(
            bpy, "V36_ThreadDark", (0.028, 0.035, 0.033, 1),
            metallic=0.58, roughness=0.42, texture_scale=30, bump_distance=0.009,
        ),
        "yellow": _material(
            bpy, "V36_SafetyYellow", (0.78, 0.45, 0.035, 1),
            metallic=0.08, roughness=0.40, texture_scale=28, bump_distance=0.008,
        ),
        "rubber": _material(
            bpy, "V36_CableRubber", (0.045, 0.055, 0.050, 1),
            metallic=0.02, roughness=0.76, texture_scale=64, bump_distance=0.016,
        ),
        "oxide": _material(
            bpy, "V36_ContactOxide", (0.22, 0.075, 0.028, 1),
            metallic=0.18, roughness=0.82, texture_scale=18, bump_distance=0.020,
        ),
    }


def _plate(name, location, half_extents, label, materials, *, width=0.06, height=0.035):
    plate = _box(bpy, name, location, half_extents, materials["plate"], bevel=0.006)
    x, y, z = location
    _text(
        bpy, f"{name}_Text", label, (x, y - half_extents[1] - 0.012, z),
        materials["ink"], size=min(width, 0.075),
    )
    for index, dx in enumerate((-half_extents[0] * 0.72, half_extents[0] * 0.72), start=1):
        _cylinder(
            bpy, f"{name}_Rivet_{index}", (x + dx, y - half_extents[1] - 0.004, z),
            0.018, 0.010, materials["black"], rotation=(math.pi / 2, 0, 0),
            vertices=16, bevel=0.003,
        )
    return plate


def _barcode(name, location, materials, *, bars=9, scale=1.0):
    x, y, z = location
    widths = (0.010, 0.018, 0.006, 0.014, 0.008, 0.022, 0.007, 0.015, 0.010)
    cursor = x - sum(widths) * scale / 2
    for index in range(min(bars, len(widths))):
        width = widths[index] * scale
        _box(
            bpy, f"{name}_{index}", (cursor + width / 2, y, z),
            (width / 2, 0.006, 0.045 * scale), materials["black"], bevel=0.001,
        )
        cursor += width + 0.008 * scale


def _threaded_stud(name, location, materials, *, radius=0.032, depth=0.075):
    x, y, z = location
    _cylinder(
        bpy, f"{name}_Core", (x, y, z), radius, depth, materials["black"],
        vertices=16, bevel=0.004,
    )
    for index in range(3):
        _torus(
            bpy, f"{name}_Thread_{index}", (x, y, z - depth * 0.28 + index * depth * 0.28),
            radius * 1.02, 0.006, materials["black"],
        )


def _add_pipe_clamps(materials):
    # Small-bore clamps and witness marks make the pipe rack read as installed,
    # maintained hardware rather than a collection of isolated cylinders.
    for index, (x, y, z, radius) in enumerate((
        (1.35, 3.12, 2.55, 0.20),
        (3.10, 3.12, 2.55, 0.20),
        (5.00, 3.12, 2.55, 0.20),
        (7.10, 3.12, 2.55, 0.20),
        (9.25, 3.12, 2.55, 0.20),
    ), start=1):
        _torus(
            bpy, f"V36_PipeClamp_{index}", (x, y, z), radius * 1.08, 0.018,
            materials["black"], rotation=(0, math.pi / 2, 0),
        )
        _box(
            bpy, f"V36_PipeClampSaddle_{index}", (x, y, z - radius - 0.055),
            (0.08, 0.13, 0.035), materials["plate"], bevel=0.008,
        )
        _threaded_stud(f"V36_PipeClampStud_{index}", (x, y, z - radius - 0.13), materials)


def _add_pump_precision(scene, materials):
    point = next((item for item in scene["waypoints"] if item["waypoint_id"] == "WP_04_PUMP"), None)
    if point is None:
        return
    x, y = float(point["x"]), float(point["y"]) + 2.2

    # Vibration sensor, cable gland and a stamped service plate on the motor.
    sensor_x, sensor_y, sensor_z = x - 0.46, y - 0.34, 1.48
    _box(bpy, "V36_PumpVibrationSensor", (sensor_x, sensor_y, sensor_z),
         (0.11, 0.08, 0.10), materials["plate"], bevel=0.018)
    _cylinder(bpy, "V36_PumpSensorGland", (sensor_x, sensor_y - 0.095, sensor_z),
              0.032, 0.05, materials["rubber"], rotation=(math.pi / 2, 0, 0),
              vertices=20, bevel=0.004)
    _pipe_between(
        bpy, "V36_PumpSensorCable", (sensor_x, sensor_y + 0.07, sensor_z),
        (x - 0.76, y - 0.18, 1.25), 0.018, materials["rubber"],
    )
    _plate("V36_PumpSensorPlate", (x - 0.30, y - 0.63, 1.63),
           (0.24, 0.018, 0.070), "VT-021", materials, width=0.045)
    _barcode("V36_PumpBarcode", (x - 0.30, y - 0.651, 1.55), materials, scale=0.72)

    # A second row of captive fasteners gives the split line a believable
    # service pattern at the hero pump angle.
    for index, angle in enumerate((0.30, 0.95, 1.60, 2.25, 2.90), start=1):
        px = x + 0.40 + math.sin(angle) * 0.42
        pz = 1.04 + math.cos(angle) * 0.42
        _threaded_stud(f"V36_PumpCoverStud_{index}", (px, y - 0.645, pz), materials,
                       radius=0.024, depth=0.036)

    # A narrow, uneven oxide witness line is deliberately physical geometry so
    # it remains visible in the low-speed robot stream as well as the macro still.
    for index, dx in enumerate((-0.62, -0.48, 0.14, 0.31), start=1):
        _box(bpy, f"V36_PumpOxideWitness_{index}", (x + dx, y - 0.592, 0.58),
             (0.025, 0.006, 0.012), materials["oxide"], bevel=0.003)


def _add_mcc_precision(scene, materials):
    point = next((item for item in scene["waypoints"] if item["waypoint_id"] == "WP_03_CABINET"), None)
    if point is None:
        return
    x, y = float(point["x"]), float(point["y"]) + 2.2

    # Ferrule rings and individual channel numbers sit on the existing front
    # terminal row and give the open cabinet a finer wiring scale.
    for index in range(8):
        fx = x - 0.57 + index * 0.16
        _torus(bpy, f"V36_MCC_FerruleRing_{index}", (fx, y - 0.708, 1.02 + (index % 3) * 0.12),
               0.034, 0.007, materials["white"], rotation=(math.pi / 2, 0, 0))
        _text(bpy, f"V36_MCC_ChannelText_{index}", f"{index + 1:02d}",
              (fx, y - 0.724, 1.02 + (index % 3) * 0.12), materials["ink"], size=0.025)

    _plate("V36_MCC_ServicePlate", (x + 0.52, y - 0.67, 2.38),
           (0.27, 0.018, 0.075), "CAB-108", materials, width=0.042)
    _barcode("V36_MCC_Barcode", (x + 0.52, y - 0.691, 2.30), materials, scale=0.70)

    # Add a thin gasket compression witness around the door and four captive
    # screws at the service edge.
    for side in (-1, 1):
        _box(bpy, f"V36_MCC_GasketWitness_{side}", (x + side * 0.74, y - 0.625, 1.47),
             (0.012, 0.008, 0.94), materials["rubber"], bevel=0.004)
    for index, z in enumerate((0.62, 1.16, 1.70, 2.24), start=1):
        _threaded_stud(f"V36_MCC_CaptiveScrew_{index}", (x + 0.83, y - 0.66, z), materials,
                       radius=0.020, depth=0.028)


def _add_vessel_precision(scene, materials):
    point = next((item for item in scene["waypoints"] if item["waypoint_id"] == "WP_02_VESSEL"), None)
    if point is None:
        return
    x, y = float(point["x"]), float(point["y"]) + 2.2
    _plate("V36_VesselInspectionPlate", (x - 0.52, y - 0.89, 2.72),
           (0.26, 0.018, 0.075), "VES-101", materials, width=0.045)
    _barcode("V36_VesselBarcode", (x - 0.52, y - 0.912, 2.64), materials, scale=0.72)
    for index, z in enumerate((0.72, 1.28, 1.84, 2.40), start=1):
        _threaded_stud(f"V36_VesselLadderStud_{index}", (x + 0.74, y - 0.86, z), materials,
                       radius=0.022, depth=0.036)


def _add_floor_precision(materials):
    # Recessed anchor sockets and drain cover fixings break up the large floor
    # planes at the same scale that a low-mounted inspection camera sees them.
    anchors = (
        (7.06, -0.75), (7.48, -0.75), (7.06, -1.18), (7.48, -1.18),
        (10.12, 0.72), (10.54, 0.72), (10.12, 0.32), (10.54, 0.32),
        (14.10, -2.10), (14.52, -2.10),
    )
    for index, (x, y) in enumerate(anchors, start=1):
        _cylinder(bpy, f"V36_FloorAnchorSocket_{index}", (x, y, 0.034),
                  0.075, 0.012, materials["black"], vertices=24, bevel=0.004)
        _threaded_stud(f"V36_FloorAnchorStud_{index}", (x, y, 0.068), materials,
                       radius=0.026, depth=0.028)
    for index, x in enumerate((4.55, 5.05, 5.55, 6.05), start=1):
        _box(bpy, f"V36_FloorJointOxide_{index}", (x, -1.26, 0.022),
             (0.045, 0.008, 0.004), materials["oxide"], bevel=0.002)


def _strengthen_material_readability():
    targets = {"V35PowderCoat", "V35LocalizedOxide", "StainlessSteel", "StructuralSteel",
               "FactoryFloor", "PumpHousing", "Cabinet", "TankCoating"}
    for material in bpy.data.materials:
        if material.name not in targets or not material.use_nodes:
            continue
        nodes = material.node_tree.nodes
        bump = nodes.get(f"{material.name}_V35ManufacturingBump")
        if bump is not None:
            if bump.inputs.get("Strength") is not None:
                bump.inputs["Strength"].default_value = 0.28
            if bump.inputs.get("Distance") is not None:
                bump.inputs["Distance"].default_value = 0.022
        roughness = nodes.get(f"{material.name}_V35RoughnessVariation")
        if roughness is not None:
            if roughness.inputs.get("To Min") is not None:
                roughness.inputs["To Min"].default_value = 0.16
            if roughness.inputs.get("To Max") is not None:
                roughness.inputs["To Max"].default_value = 0.82


def main() -> int:
    args = _args()
    bpy.ops.wm.open_mainfile(filepath=str(args.input))
    scene = json.loads(args.scene_input.read_text(encoding="utf-8"))
    materials = _precision_materials()
    _strengthen_material_readability()
    _add_pipe_clamps(materials)
    _add_pump_precision(scene, materials)
    _add_mcc_precision(scene, materials)
    _add_vessel_precision(scene, materials)
    _add_floor_precision(materials)
    bpy.context.scene["scene_detail_level"] = "factory_environment_v36_precision_inspection_realism"
    bpy.context.scene["precision_pass"] = "serial_plates_ferrules_clamps_sensor_cables_anchor_sockets"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(args.output))
    print("V36_PRECISION_PASS=APPLIED", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
