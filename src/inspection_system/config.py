from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from .models import Waypoint


class ConfigError(ValueError):
    """Raised when a site configuration is missing or inconsistent."""


def _require_text(value: Any, label: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{label} 必须是非空字符串。")


def _require_finite_number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(f"{label} 必须是有限数字。")
    try:
        number = float(value)
    except (OverflowError, ValueError) as exc:
        raise ConfigError(f"{label} 必须是有限数字。") from exc
    if not math.isfinite(number):
        raise ConfigError(f"{label} 必须是有限数字。")
    return number


def _reject_nonstandard_json_number(value: str) -> None:
    raise ConfigError(f"JSON 不能包含非标准数值: {value}。")


def load_site_config(path: str | Path) -> dict[str, Any]:
    config_path = Path(path)
    try:
        data = json.loads(
            config_path.read_text(encoding="utf-8"),
            parse_constant=_reject_nonstandard_json_number,
        )
    except FileNotFoundError as exc:
        raise ConfigError(f"配置文件不存在: {config_path}") from exc
    except UnicodeDecodeError as exc:
        raise ConfigError(f"配置文件不是有效的 UTF-8: {config_path}") from exc
    except json.JSONDecodeError as exc:
        raise ConfigError(f"JSON 格式错误: {config_path}: {exc}") from exc
    except OSError as exc:
        raise ConfigError(f"配置文件无法读取: {config_path}") from exc

    if not isinstance(data, dict):
        raise ConfigError("配置根节点必须是 JSON object。")
    for key in ("site_id", "site_name", "robot", "waypoints"):
        if key not in data:
            raise ConfigError(f"缺少必需字段: {key}")
    _require_text(data["site_id"], "site_id")
    _require_text(data["site_name"], "site_name")
    if not isinstance(data["robot"], dict):
        raise ConfigError("robot 必须是 JSON object。")
    _require_text(data["robot"].get("robot_id"), "robot.robot_id")
    if not isinstance(data["waypoints"], list) or not data["waypoints"]:
        raise ConfigError("waypoints 必须是非空数组。")

    ids: set[str] = set()
    for index, item in enumerate(data["waypoints"]):
        if not isinstance(item, dict):
            raise ConfigError(f"waypoints[{index}] 必须是 object。")
        required = ("waypoint_id", "device_id", "device_name", "zone", "position",
                    "yaw_deg", "warning_temp_c", "critical_temp_c")
        missing = [field for field in required if field not in item]
        if missing:
            raise ConfigError(f"waypoints[{index}] 缺少字段: {', '.join(missing)}")
        waypoint_id = item["waypoint_id"]
        for field in ("waypoint_id", "device_id", "device_name", "zone"):
            _require_text(item[field], f"waypoints[{index}].{field}")
        if waypoint_id in ids:
            raise ConfigError(f"waypoint_id 重复: {waypoint_id}")
        ids.add(waypoint_id)
        pos = item["position"]
        if not isinstance(pos, dict) or any(k not in pos for k in ("x", "y", "z")):
            raise ConfigError(f"{waypoint_id}.position 必须包含 x/y/z。")
        for axis in ("x", "y", "z"):
            _require_finite_number(pos[axis], f"{waypoint_id}.position.{axis}")
        _require_finite_number(item["yaw_deg"], f"{waypoint_id}.yaw_deg")
        warning = _require_finite_number(
            item["warning_temp_c"], f"{waypoint_id}.warning_temp_c")
        critical = _require_finite_number(
            item["critical_temp_c"], f"{waypoint_id}.critical_temp_c")
        if critical < warning:
            raise ConfigError(f"{waypoint_id}: critical_temp_c 不能低于 warning_temp_c。")
        pressure_limit = item.get("pressure_max_mpa")
        if pressure_limit is not None:
            pressure_limit = _require_finite_number(
                pressure_limit, f"{waypoint_id}.pressure_max_mpa")
            if pressure_limit <= 0:
                raise ConfigError(f"{waypoint_id}: pressure_max_mpa 必须大于 0 或为 null。")
        require_door_closed = item.get("require_door_closed", False)
        if not isinstance(require_door_closed, bool):
            raise ConfigError(f"{waypoint_id}.require_door_closed 必须是布尔值。")
    return data


def waypoints_from_config(config: dict[str, Any]) -> list[Waypoint]:
    waypoints: list[Waypoint] = []
    for item in config["waypoints"]:
        pos = item["position"]
        waypoints.append(Waypoint(
            waypoint_id=str(item["waypoint_id"]),
            device_id=str(item["device_id"]),
            device_name=str(item["device_name"]),
            zone=str(item["zone"]),
            asset_id=(str(item["asset_id"]) if item.get("asset_id") is not None else None),
            x=float(pos["x"]), y=float(pos["y"]), z=float(pos["z"]),
            yaw_deg=float(item["yaw_deg"]),
            pressure_max_mpa=(
                float(item["pressure_max_mpa"])
                if item.get("pressure_max_mpa") is not None else None
            ),
            warning_temp_c=float(item["warning_temp_c"]),
            critical_temp_c=float(item["critical_temp_c"]),
            require_door_closed=bool(item.get("require_door_closed", False)),
        ))
    return waypoints
