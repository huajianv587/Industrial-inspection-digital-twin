from __future__ import annotations
import json
import random
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from .models import Observation, Waypoint

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

def reference_observation(waypoint: Waypoint, robot_id: str, index: int) -> Observation:
    """Fixed illustrative observation for the offline end-to-end demo."""
    cases: dict[str, dict[str, Any]] = {
        "WP_01_PIPE": {"pressure_mpa": 0.86, "temperature_c": 62.4,
            "ambient_temperature_c": 26.5, "cabinet_door_closed": None, "leak_detected": False},
        "WP_02_CABINET": {"pressure_mpa": None, "temperature_c": 48.3,
            "ambient_temperature_c": 26.5, "cabinet_door_closed": False, "leak_detected": None},
        "WP_03_PUMP": {"pressure_mpa": 1.32, "temperature_c": 51.2,
            "ambient_temperature_c": 26.5, "cabinet_door_closed": None, "leak_detected": True},
    }
    values = cases.get(waypoint.waypoint_id, {
        "pressure_mpa": None, "temperature_c": 35.0,
        "ambient_temperature_c": 26.5, "cabinet_door_closed": None, "leak_detected": False})
    return Observation(
        sample_id=f"demo-{index:03d}-{waypoint.waypoint_id}", timestamp_utc=_now_iso(),
        source="synthetic_simulation", robot_id=robot_id,
        waypoint_id=waypoint.waypoint_id, device_id=waypoint.device_id, **values,
        sensor_confidence={"gauge": 0.96 if values["pressure_mpa"] is not None else 0.0,
                           "thermal": 0.92, "state": 0.90},
        quality_flags=["SYNTHETIC_INPUT", "NO_RENDERED_IMAGE"],
        domain={"rendered_image_available": False, "scenario": "fixed_demo_case"})

def generate_dataset(waypoints: list[Waypoint], robot_id: str, count: int,
                     seed: int = 42) -> list[dict[str, Any]]:
    """Generate structured rule-labeled records for pipeline testing.

    These records are not rendered images, human annotations, or evidence of
    model accuracy. `scenario_label` is assigned by the generator.
    """
    if count < 1:
        raise ValueError("count 必须大于 0。")
    rng = random.Random(seed)
    scenarios = ("normal", "overheat", "pressure_high", "door_open", "leak", "sensor_dropout")
    records: list[dict[str, Any]] = []
    for index in range(count):
        scenario = scenarios[index % len(scenarios)]
        if scenario == "pressure_high":
            candidates = [w for w in waypoints if w.pressure_max_mpa is not None]
        elif scenario == "door_open":
            candidates = [w for w in waypoints if w.require_door_closed]
        else:
            candidates = waypoints
        if not candidates:
            candidates = waypoints
        waypoint = candidates[index % len(candidates)]
        pressure: float | None = None
        temperature: float | None = round(rng.uniform(34.0, 49.0), 2)
        door: bool | None = True if waypoint.require_door_closed else None
        leak: bool | None = False
        ambient = round(rng.uniform(22.0, 30.0), 2)
        if waypoint.pressure_max_mpa is not None:
            pressure = round(rng.uniform(0.35, min(waypoint.pressure_max_mpa, 1.0)), 3)
        if scenario == "overheat":
            low = max(waypoint.critical_temp_c, 60.0)
            temperature = round(rng.uniform(low, low + 25.0), 2)
        elif scenario == "pressure_high" and waypoint.pressure_max_mpa is not None:
            pressure = round(waypoint.pressure_max_mpa * rng.uniform(1.02, 1.25), 3)
        elif scenario == "door_open":
            door = False
        elif scenario == "leak":
            leak = True
        elif scenario == "sensor_dropout":
            pressure, temperature, door, leak = None, None, None, None
        expected_codes: list[str] = []
        if scenario == "overheat":
            expected_codes.append("TEMPERATURE_CRITICAL")
        elif scenario == "pressure_high" and pressure is not None:
            expected_codes.append("PRESSURE_HIGH_OR_CRITICAL")
        elif scenario == "door_open":
            expected_codes.append("CABINET_DOOR_OPEN")
        elif scenario == "leak":
            expected_codes.append("LEAK_SUSPECTED")
        elif scenario == "sensor_dropout":
            expected_codes.append("DATA_QUALITY_UNKNOWN")
        records.append({
            "schema_version": "1.0", "sample_id": f"syn-{seed:04d}-{index:06d}",
            "source": "synthetic_rule_based", "robot_id": robot_id,
            "waypoint_id": waypoint.waypoint_id, "device_id": waypoint.device_id,
            "timestamp_utc": _now_iso(),
            "observation": {"pressure_mpa": pressure, "temperature_c": temperature,
                "ambient_temperature_c": ambient, "cabinet_door_closed": door,
                "leak_detected": leak},
            "scenario_label": scenario, "expected_anomaly_codes": expected_codes,
            "domain_randomization": {"lighting": rng.choice(["bright", "dim", "mixed"]),
                "camera_distance_m": round(rng.uniform(0.6, 2.8), 2),
                "view_angle_deg": round(rng.uniform(-35.0, 35.0), 1),
                "surface_condition": rng.choice(["clean", "dusty", "stained"])},
            "limitations": ["no_rendered_rgb_or_depth_image",
                "no_radiometric_thermal_simulation", "scenario_label_is_generator_assigned"]})
    return records

def write_jsonl(records: Iterable[dict[str, Any]], path: str | Path) -> int:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with output.open("w", encoding="utf-8") as stream:
        for record in records:
            stream.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
            count += 1
    return count
