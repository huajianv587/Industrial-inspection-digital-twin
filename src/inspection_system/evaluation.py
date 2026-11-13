from __future__ import annotations
from dataclasses import dataclass, asdict
import json
from pathlib import Path
from typing import Any
from .config import load_site_config, waypoints_from_config
from .models import Observation, Severity
from .perception.rules import RuleBasedDiagnosticEngine

@dataclass
class AcceptanceCheck:
    name: str
    passed: bool
    expected: str
    actual: str

def run_acceptance_suite(config_path: str | Path) -> dict[str, Any]:
    """Run deterministic software acceptance checks, not an ML accuracy benchmark."""
    config = load_site_config(config_path)
    waypoints = waypoints_from_config(config)
    by_id = {item.waypoint_id: item for item in waypoints}
    engine = RuleBasedDiagnosticEngine()
    checks: list[AcceptanceCheck] = []

    pipe = by_id.get("WP_01_PIPE", waypoints[0])
    hot = Observation("eval-hot", "2026-01-01T00:00:00+00:00", "synthetic_simulation",
        "eval-robot", pipe.waypoint_id, pipe.device_id, pressure_mpa=0.8,
        temperature_c=pipe.critical_temp_c + 5, ambient_temperature_c=25)
    result = engine.assess(hot, pipe)
    checks.append(AcceptanceCheck("critical_temperature_flagged",
        result.severity == Severity.CRITICAL and "TEMPERATURE_CRITICAL" in [a.code for a in result.anomalies],
        "CRITICAL + TEMPERATURE_CRITICAL", f"{result.severity.value} + {','.join(a.code for a in result.anomalies)}"))

    if pipe.pressure_max_mpa is not None:
        pressure_obs = Observation("eval-pressure", "2026-01-01T00:00:00+00:00", "synthetic_simulation",
            "eval-robot", pipe.waypoint_id, pipe.device_id,
            pressure_mpa=pipe.pressure_max_mpa * 1.2, temperature_c=35, ambient_temperature_c=25)
        pressure_result = engine.assess(pressure_obs, pipe)
        pressure_ok = pressure_result.severity == Severity.CRITICAL and any(
            a.code == "PRESSURE_CRITICAL" for a in pressure_result.anomalies)
        checks.append(AcceptanceCheck("high_pressure_flagged", pressure_ok,
            "CRITICAL + PRESSURE_CRITICAL",
            f"{pressure_result.severity.value} + {','.join(a.code for a in pressure_result.anomalies)}"))

    door_waypoint = next((w for w in waypoints if w.require_door_closed), None)
    if door_waypoint:
        door_obs = Observation("eval-door", "2026-01-01T00:00:00+00:00", "synthetic_simulation",
            "eval-robot", door_waypoint.waypoint_id, door_waypoint.device_id,
            temperature_c=35, ambient_temperature_c=25, cabinet_door_closed=False)
        door_result = engine.assess(door_obs, door_waypoint)
        checks.append(AcceptanceCheck("open_door_flagged",
            any(a.code == "CABINET_DOOR_OPEN" for a in door_result.anomalies),
            "CABINET_DOOR_OPEN", ",".join(a.code for a in door_result.anomalies) or "no anomaly"))

    empty = Observation("eval-empty", "2026-01-01T00:00:00+00:00", "synthetic_simulation",
        "eval-robot", pipe.waypoint_id, pipe.device_id)
    empty_result = engine.assess(empty, pipe)
    checks.append(AcceptanceCheck("empty_observation_is_unknown",
        empty_result.severity == Severity.UNKNOWN, "UNKNOWN", empty_result.severity.value))

    passed = sum(item.passed for item in checks)
    return {
        "suite": "deterministic_software_acceptance_not_model_accuracy",
        "config": str(config_path),
        "checks_passed": passed,
        "checks_total": len(checks),
        "acceptance_pass_rate": round(passed / len(checks), 4) if checks else 0.0,
        "checks": [asdict(item) for item in checks],
        "warning": "该通过率只表示固定软件验收用例通过比例，不是模型准确率或现场表现。",
    }

def write_acceptance_report(report: dict[str, Any], path: str | Path) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
