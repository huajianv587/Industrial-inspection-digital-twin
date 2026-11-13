#!/usr/bin/env python3
"""Minimal Isaac Sim scene bootstrap; requires an installed Isaac Sim runtime.

This script creates generic geometric placeholders only. It intentionally does
not claim to load a Unitree asset or configure production-grade sensors.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys

def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="configs/site.json")
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--steps", type=int, default=600)
    return parser.parse_args()

def main() -> int:
    args = parse_args()
    config_path = Path(args.config)
    if not config_path.exists():
        print(f"Config not found: {config_path}", file=sys.stderr)
        return 2
    config = json.loads(config_path.read_text(encoding="utf-8"))
    try:
        from isaacsim import SimulationApp
    except ImportError:
        try:
            from omni.isaac.kit import SimulationApp
        except ImportError as exc:
            print("Isaac Sim runtime was not found. Run this script with the Isaac Sim Python launcher.",
                  file=sys.stderr)
            raise RuntimeError("SimulationApp import failed") from exc

    app = SimulationApp({"headless": args.headless})
    try:
        try:
            from isaacsim.core.api import World
            from isaacsim.core.api.objects import FixedCuboid
        except ImportError:
            from omni.isaac.core import World
            from omni.isaac.core.objects import FixedCuboid

        world = World(stage_units_in_meters=1.0, physics_dt=1.0 / 60.0, rendering_dt=1.0 / 30.0)
        world.scene.add_default_ground_plane()
        # Generic cuboid placeholder, not a Unitree robot asset.
        world.scene.add(FixedCuboid(
            prim_path="/World/RobotPlaceholder", name="robot_placeholder",
            position=[0.0, 0.0, 0.35], size=0.45, color=[0.15, 0.35, 0.75]))
        for item in config["waypoints"]:
            pos = item["position"]
            world.scene.add(FixedCuboid(
                prim_path=f"/World/Devices/{item['device_id']}",
                name=item["device_id"],
                position=[float(pos["x"]), float(pos["y"]), 0.75],
                size=0.8, color=[0.55, 0.58, 0.60]))
        world.reset()
        print(f"Scene initialized for {config['site_id']}; robot is a generic placeholder.")
        for _ in range(max(1, args.steps)):
            world.step(render=not args.headless)
        print("Scene bootstrap finished. No Unitree asset, sensors, ROS 2 bridge, or navigation were configured.")
    finally:
        app.close()
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
