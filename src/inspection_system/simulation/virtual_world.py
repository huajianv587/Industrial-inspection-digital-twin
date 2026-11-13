from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import html
import json
import math
from pathlib import Path
import shutil
import subprocess
from typing import Any, Literal

from ..models import InspectionRun, Observation, Waypoint
from ..synthetic import reference_observation

RenderBackend = Literal["svg", "blender", "auto"]
RenderQuality = Literal["preview", "production", "ultra"]


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _safe_name(value: str) -> str:
    return "".join(character if character.isalnum() or character in "._-" else "_"
                   for character in value)


def _json_write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _scene_bounds(waypoints: list[Waypoint], trajectory: list[dict[str, Any]]) -> tuple[float, float, float, float]:
    points = [(0.0, 0.0)]
    points.extend((item.x, item.y) for item in waypoints)
    points.extend((float(item["x"]), float(item["y"])) for item in trajectory)
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    padding = 2.5
    return min(xs) - padding, max(xs) + padding, min(ys) - padding, max(ys) + padding


def _project(x: float, y: float, bounds: tuple[float, float, float, float],
             *, width: float, height: float, margin: float) -> tuple[float, float]:
    min_x, max_x, min_y, max_y = bounds
    usable_width = width - 2 * margin
    usable_height = height - 2 * margin
    span_x = max(max_x - min_x, 1.0)
    span_y = max(max_y - min_y, 1.0)
    scale = min(usable_width / span_x, usable_height / span_y)
    map_width = span_x * scale
    map_height = span_y * scale
    origin_x = (width - map_width) / 2
    origin_y = (height - map_height) / 2
    return origin_x + (x - min_x) * scale, origin_y + (max_y - y) * scale


def render_scene_svg(
    *,
    site_id: str,
    waypoints: list[Waypoint],
    trajectory: list[dict[str, Any]],
    output_path: Path,
    focus_waypoint_id: str | None = None,
    title: str = "Local virtual inspection world",
) -> None:
    """Render a dependency-free top-down scene for local replay and review."""
    width, height, margin = 1280, 760, 64
    bounds = _scene_bounds(waypoints, trajectory)
    route = [_project(0.0, 0.0, bounds, width=width, height=height, margin=margin)]
    route.extend(_project(item.x, item.y, bounds, width=width, height=height, margin=margin)
                 for item in waypoints)
    route_points = " ".join(f"{x:.1f},{y:.1f}" for x, y in route)
    current = trajectory[-1] if trajectory else {"x": 0.0, "y": 0.0, "yaw_deg": 0.0}
    robot_x, robot_y = _project(float(current["x"]), float(current["y"]), bounds,
                                width=width, height=height, margin=margin)
    robot_yaw = float(current.get("yaw_deg", 0.0))

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
        f'role="img" aria-labelledby="scene-title scene-desc">',
        f"<title id=\"scene-title\">{html.escape(title)}</title>",
        f"<desc id=\"scene-desc\">Synthetic local virtual world for {html.escape(site_id)}; "
        "not a live robot map.</desc>",
        '<rect width="1280" height="760" fill="#eef2ed"/>',
        '<rect x="30" y="30" width="1220" height="700" rx="8" fill="#f8faf7" '
        'stroke="#c7d2c7" stroke-width="2"/>',
        '<text x="64" y="78" fill="#1e2e25" font-family="Arial, sans-serif" '
        'font-size="24" font-weight="700">Local Virtual Inspection World</text>',
        f'<text x="64" y="104" fill="#506056" font-family="monospace" font-size="14">'
        f'{html.escape(site_id)} · synthetic_simulation · kinematic replay</text>',
        '<g stroke="#d9e1da" stroke-width="1">',
    ]
    for grid in range(80, 1220, 40):
        parts.append(f'<path d="M {grid} 130 V 690"/>')
    for grid in range(150, 700, 40):
        parts.append(f'<path d="M 70 {grid} H 1210"/>')
    parts.append('</g>')
    parts.append(f'<polyline points="{route_points}" fill="none" stroke="#47745a" '
                 'stroke-width="5" stroke-linecap="round" stroke-linejoin="round" opacity=".55"/>')

    for index, waypoint in enumerate(waypoints, start=1):
        x, y = _project(waypoint.x, waypoint.y, bounds, width=width, height=height, margin=margin)
        focused = waypoint.waypoint_id == focus_waypoint_id
        fill = "#d49b3f" if focused else "#6a8873"
        parts.append(f'<g aria-label="{html.escape(waypoint.waypoint_id)}">')
        parts.append(f'<rect x="{x - 24:.1f}" y="{y - 18:.1f}" width="48" height="36" '
                     f'rx="4" fill="{fill}" stroke="#263b2d" stroke-width="2"/>')
        parts.append(f'<text x="{x:.1f}" y="{y + 5:.1f}" text-anchor="middle" '
                     'fill="white" font-family="monospace" font-size="12" font-weight="700">'
                     f'P{index}</text>')
        parts.append(f'<text x="{x + 34:.1f}" y="{y - 8:.1f}" fill="#263b2d" '
                     'font-family="Arial, sans-serif" font-size="13" font-weight="700">'
                     f'{html.escape(waypoint.device_id)}</text>')
        parts.append(f'<text x="{x + 34:.1f}" y="{y + 12:.1f}" fill="#506056" '
                     'font-family="Arial, sans-serif" font-size="12">'
                     f'{html.escape(waypoint.zone)}</text>')
        parts.append('</g>')

    parts.extend([
        f'<g transform="translate({robot_x:.1f} {robot_y:.1f}) rotate({-robot_yaw:.1f})" '
        'aria-label="virtual robot">',
        '<rect x="-22" y="-14" width="44" height="28" rx="7" fill="#2b5d9a" '
        'stroke="#19385d" stroke-width="3"/>',
        '<circle cx="16" cy="0" r="5" fill="#d9efff" stroke="#19385d" stroke-width="2"/>',
        '<path d="M -13 -14 V -25 M 13 -14 V -25 M -13 14 V 25 M 13 14 V 25" '
        'stroke="#19385d" stroke-width="5" stroke-linecap="round"/>',
        '</g>',
        f'<text x="{robot_x + 28:.1f}" y="{robot_y - 20:.1f}" fill="#19385d" '
        'font-family="monospace" font-size="13" font-weight="700">ROBOT</text>',
        '<g transform="translate(72 650)">',
        '<rect width="340" height="62" rx="5" fill="#ffffff" stroke="#c7d2c7"/>',
        '<circle cx="20" cy="22" r="8" fill="#2b5d9a"/><text x="38" y="27" '
        'font-family="Arial, sans-serif" font-size="13" fill="#263b2d">virtual robot pose</text>',
        '<line x1="12" y1="43" x2="28" y2="43" stroke="#47745a" stroke-width="4"/>'
        '<text x="38" y="48" font-family="Arial, sans-serif" font-size="13" fill="#263b2d">'
        'planned route</text>',
        '</g>',
        '<text x="1210" y="705" text-anchor="end" fill="#65746a" '
        'font-family="monospace" font-size="12">rendered locally · no real sensor data</text>',
        '</svg>',
    ])
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(parts) + "\n", encoding="utf-8")


@dataclass
class VirtualWorldRobotAdapter:
    """Kinematic robot and sensor adapter for a fully local virtual run."""

    site_id: str
    robot_id: str
    waypoints: list[Waypoint]
    output_dir: Path
    seed: int = 42
    render_backend: RenderBackend = "svg"
    render_quality: RenderQuality = "production"
    render_resolution: int = 1280
    fail_waypoints: set[str] = field(default_factory=set)
    event_log: list[dict[str, Any]] = field(default_factory=list)
    source = "synthetic_simulation"

    def __post_init__(self) -> None:
        if self.render_backend not in {"svg", "blender", "auto"}:
            raise ValueError("render_backend must be svg, blender, or auto.")
        if self.render_quality not in {"preview", "production", "ultra"}:
            raise ValueError("render_quality must be preview, production, or ultra.")
        if isinstance(self.render_resolution, bool) or not isinstance(self.render_resolution, int):
            raise ValueError("render_resolution must be an integer.")
        if self.render_resolution < 640 or self.render_resolution > 4096:
            raise ValueError("render_resolution must be between 640 and 4096.")
        if isinstance(self.seed, bool) or not isinstance(self.seed, int) or self.seed < 0:
            raise ValueError("seed must be a non-negative integer.")
        self.output_dir = Path(self.output_dir)
        blender = shutil.which("blender")
        if self.render_backend == "blender" and blender is None:
            raise RuntimeError("Blender was requested but no blender executable was found.")
        self.resolved_backend = (
            "blender" if self.render_backend == "auto" and blender
            else "svg" if self.render_backend == "auto"
            else self.render_backend
        )
        self._blender = blender
        self._pose = {"x": 0.0, "y": 0.0, "z": 0.0, "yaw_deg": 0.0}
        self._trajectory: list[dict[str, Any]] = [self._pose.copy()]
        self._observation_artifacts: dict[str, str] = {}
        self._captured: list[dict[str, Any]] = []
        self.additional_artifacts: dict[str, Path] = {}

    def navigate(self, waypoint: Waypoint) -> bool:
        if waypoint.waypoint_id in self.fail_waypoints:
            self.event_log.append({"event": "navigation_failed", "waypoint_id": waypoint.waypoint_id})
            return False
        start_x, start_y = float(self._pose["x"]), float(self._pose["y"])
        distance = math.hypot(waypoint.x - start_x, waypoint.y - start_y)
        steps = max(1, min(40, math.ceil(distance / 0.5)))
        for step in range(1, steps + 1):
            fraction = step / steps
            self._pose = {
                "x": round(start_x + (waypoint.x - start_x) * fraction, 4),
                "y": round(start_y + (waypoint.y - start_y) * fraction, 4),
                "z": round(waypoint.z, 4),
                "yaw_deg": round(waypoint.yaw_deg, 3),
            }
            self._trajectory.append(self._pose.copy())
        self.event_log.append({
            "event": "navigation_succeeded",
            "waypoint_id": waypoint.waypoint_id,
            "distance_m": round(distance, 4),
            "steps": steps,
        })
        return True

    def capture(self, waypoint: Waypoint, index: int) -> Observation:
        observation = reference_observation(waypoint, self.robot_id, index)
        artifact_extension = "png" if self.resolved_backend == "blender" else "svg"
        artifact_name = (
            f"virtual_world__{_safe_name(waypoint.waypoint_id)}__rgb_camera.{artifact_extension}"
        )
        observation.quality_flags = ["SYNTHETIC_INPUT", "VIRTUAL_WORLD_RENDER"]
        observation.domain = {
            **observation.domain,
            **({"asset_id": waypoint.asset_id} if waypoint.asset_id else {}),
            "rendered_image_available": True,
            "virtual_world": True,
            "virtual_world_engine": "local_kinematic",
            "render_backend": self.resolved_backend,
            "render_quality": self.render_quality,
            "render_resolution": self.render_resolution,
            "seed": self.seed,
            "robot_pose": self._pose.copy(),
            "sensor_provenance": {
                "sensor_ids": ["rgb_camera"],
                "frame_id": "virtual_world/base_link/rgb_camera",
                "artifacts": [{
                    "name": artifact_name,
                    "sensor_id": "rgb_camera",
                    "media_type": "image/png" if artifact_extension == "png" else "image/svg+xml",
                    "timestamp_utc": observation.timestamp_utc,
                }],
            },
            "limitations": [
                "kinematic_robot_not_physical_dynamics",
                "synthetic_sensor_values",
                "not_a_calibrated_thermal_or_depth_measurement",
            ],
        }
        self._observation_artifacts[waypoint.waypoint_id] = artifact_name
        self._captured.append({
            "waypoint_id": waypoint.waypoint_id,
            "timestamp_utc": observation.timestamp_utc,
            "pose": self._pose.copy(),
        })
        self.event_log.append({"event": "virtual_capture", "waypoint_id": waypoint.waypoint_id,
                               "artifact": artifact_name})
        return observation

    def finalize(self, run: InspectionRun) -> None:
        virtual_dir = self.output_dir / "virtual_world"
        virtual_dir.mkdir(parents=True, exist_ok=True)
        scene_input = {
            "schema_version": 1,
            "site_id": self.site_id,
            "robot_id": self.robot_id,
            "seed": self.seed,
            "waypoints": [{
                "waypoint_id": item.waypoint_id,
                "device_id": item.device_id,
                "device_name": item.device_name,
                "zone": item.zone,
                "asset_id": getattr(item, "asset_id", None),
                "x": item.x,
                "y": item.y,
                "z": item.z,
                "yaw_deg": item.yaw_deg,
            } for item in self.waypoints],
            "trajectory": self._trajectory,
            "captured": self._captured,
        }
        scene_input_path = virtual_dir / "scene_input.json"
        _json_write(scene_input_path, scene_input)
        trajectory_path = virtual_dir / "trajectory.json"
        _json_write(trajectory_path, {
            "run_id": run.run_id,
            "source": run.source,
            "engine": "local_kinematic",
            "seed": self.seed,
            "events": self.event_log,
            "trajectory": self._trajectory,
        })

        if self.resolved_backend == "blender":
            self._render_blender(scene_input_path, virtual_dir)
        else:
            for waypoint in self.waypoints:
                artifact_name = self._observation_artifacts.get(waypoint.waypoint_id)
                if artifact_name is None:
                    continue
                render_scene_svg(
                    site_id=self.site_id,
                    waypoints=self.waypoints,
                    trajectory=self._trajectory,
                    output_path=virtual_dir / artifact_name,
                    focus_waypoint_id=waypoint.waypoint_id,
                    title=f"Virtual inspection view: {waypoint.waypoint_id}",
                )
            render_scene_svg(
                site_id=self.site_id,
                waypoints=self.waypoints,
                trajectory=self._trajectory,
                output_path=virtual_dir / "overview.svg",
                title="Local virtual inspection overview",
            )

        scene_artifact_names = sorted(
            path.name for path in virtual_dir.iterdir()
            if path.is_file()
            and not path.name.startswith("._")
            and path.name != "virtual_world_manifest.json"
        )
        manifest_path = virtual_dir / "virtual_world_manifest.json"
        _json_write(manifest_path, {
            "schema_version": 1,
            "run_id": run.run_id,
            "site_id": self.site_id,
            "robot_id": self.robot_id,
            "engine": "local_kinematic",
            "requested_render_backend": self.render_backend,
            "resolved_render_backend": self.resolved_backend,
            "render_quality": self.render_quality,
            "render_resolution": self.render_resolution,
            "seed": self.seed,
            "rendered_waypoints": list(self._observation_artifacts),
            "scene_artifacts": scene_artifact_names + [manifest_path.name],
            "limitations": [
                "This is a local virtual-world execution, not Isaac Sim, ROS 2, or a physical robot.",
                "The robot is a procedural placeholder and does not model Unitree dynamics.",
                "Sensor values are scenario inputs used to exercise the inspection workflow.",
            ],
        })
        if self.resolved_backend == "blender":
            self._attach_scene_artifacts(run, scene_artifact_names)
            self.additional_artifacts = {
                name: virtual_dir / name
                for name in scene_artifact_names
            }
        else:
            self.additional_artifacts = {
                name: virtual_dir / name
                for name in self._observation_artifacts.values()
            }

    @staticmethod
    def _artifact_media_type(name: str) -> str:
        suffix = Path(name).suffix.lower()
        return {
            ".png": "image/png",
            ".svg": "image/svg+xml",
            ".json": "application/json",
            ".glb": "model/gltf-binary",
            ".blend": "application/octet-stream",
        }.get(suffix, "application/octet-stream")

    def _attach_scene_artifacts(self, run: InspectionRun, names: list[str]) -> None:
        """Reference multi-camera scene files through the existing provenance contract."""
        target = next((item.observation for item in run.results if item.observation), None)
        if target is None:
            return
        provenance = target.domain.setdefault("sensor_provenance", {
            "sensor_ids": [], "frame_id": "virtual_world/base_link/rgb_camera", "artifacts": [],
        })
        sensor_ids = provenance.setdefault("sensor_ids", [])
        if "virtual_scene" not in sensor_ids:
            sensor_ids.append("virtual_scene")
        references = provenance.setdefault("artifacts", [])
        existing = {item.get("name") for item in references if isinstance(item, dict)}
        # Per-waypoint RGB captures are already referenced by the observation
        # created at that waypoint. Keep those one-to-one references intact and
        # attach only global scene/camera files to the scene provenance record.
        waypoint_capture_names = set(self._observation_artifacts.values())
        for name in names:
            if name in existing or name in waypoint_capture_names:
                continue
            references.append({
                "name": name,
                "sensor_id": "virtual_scene",
                "media_type": self._artifact_media_type(name),
                "timestamp_utc": target.timestamp_utc,
            })
        target.domain["virtual_scene_artifacts"] = {
            "unit_scale": "1 Blender unit = 1 metre",
            "multi_camera": True,
            "artifact_names": names,
        }

    def _render_blender(self, scene_input_path: Path, output_dir: Path) -> None:
        if not self._blender:
            raise RuntimeError("Blender executable is unavailable for the requested renderer.")
        script = Path(__file__).resolve().parents[3] / "blender_sim" / "render_factory.py"
        # Full industrial scenes can contain dozens of synchronized cameras;
        # allow a complete local render to finish instead of failing at the
        # ten-minute mark while Blender is still exporting camera artifacts.
        completed = subprocess.run([
            self._blender, "--background", "--python", str(script), "--",
            "--scene-input", str(scene_input_path), "--output-dir", str(output_dir),
            "--resolution", str(self.render_resolution),
            "--quality", self.render_quality,
        ], capture_output=True, text=True, timeout=3600, check=False)
        scene_file = output_dir / "factory_scene.blend"
        if completed.returncode != 0 or not scene_file.is_file():
            detail = (completed.stderr or completed.stdout).strip()[-1000:]
            if completed.returncode == 0:
                detail = f"Blender exited successfully but did not create {scene_file.name}. {detail}"
            raise RuntimeError(f"Blender render failed with exit code {completed.returncode}: {detail}")
