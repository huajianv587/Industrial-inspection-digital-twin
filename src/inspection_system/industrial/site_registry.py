from __future__ import annotations

from pathlib import Path
from typing import Any

from ..config import ConfigError, load_site_config


class IndustrialSiteError(ConfigError):
    """Raised when a site file is not complete enough for industrial use."""


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise IndustrialSiteError(f"{label} must be a non-empty string.")
    return value


def _list(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list) or not value:
        raise IndustrialSiteError(f"{label} must be a non-empty array.")
    return value


def load_industrial_site(path: str | Path) -> dict[str, Any]:
    """Load the normal site contract plus the industrial asset registry.

    The registry intentionally keeps model provenance explicit. A procedural
    proxy can make the local demo runnable, but it never counts as a field-
    verified CAD, scan, or calibrated sensor source.
    """
    try:
        data = load_site_config(path)
    except ConfigError as exc:
        raise IndustrialSiteError(str(exc)) from exc

    profile = data.get("industrial_profile")
    if not isinstance(profile, dict):
        raise IndustrialSiteError("industrial_profile is required for an industrial site.")
    _text(profile.get("plant_type"), "industrial_profile.plant_type")
    _text(profile.get("coordinate_system"), "industrial_profile.coordinate_system")
    _text(profile.get("unit_system"), "industrial_profile.unit_system")

    zones = _list(data.get("zones"), "zones")
    zone_ids: set[str] = set()
    for index, zone in enumerate(zones):
        if not isinstance(zone, dict):
            raise IndustrialSiteError(f"zones[{index}] must be an object.")
        zone_id = _text(zone.get("zone_id"), f"zones[{index}].zone_id")
        _text(zone.get("name"), f"zones[{index}].name")
        if zone_id in zone_ids:
            raise IndustrialSiteError(f"Duplicate zone_id: {zone_id}")
        zone_ids.add(zone_id)

    assets = _list(data.get("assets"), "assets")
    asset_ids: set[str] = set()
    allowed_model_status = {"procedural_proxy", "cad_pending", "field_verified"}
    for index, asset in enumerate(assets):
        if not isinstance(asset, dict):
            raise IndustrialSiteError(f"assets[{index}] must be an object.")
        asset_id = _text(asset.get("asset_id"), f"assets[{index}].asset_id")
        _text(asset.get("asset_type"), f"assets[{index}].asset_type")
        zone_id = _text(asset.get("zone_id"), f"assets[{index}].zone_id")
        _text(asset.get("display_name"), f"assets[{index}].display_name")
        model_status = _text(asset.get("model_status"), f"assets[{index}].model_status")
        if zone_id not in zone_ids:
            raise IndustrialSiteError(f"{asset_id} references unknown zone_id: {zone_id}")
        if model_status not in allowed_model_status:
            raise IndustrialSiteError(
                f"{asset_id}.model_status must be one of {sorted(allowed_model_status)}."
            )
        _text(asset.get("model_asset"), f"assets[{index}].model_asset")
        inspection_points = _list(asset.get("inspection_points"),
                                  f"assets[{index}].inspection_points")
        for point_index, point in enumerate(inspection_points):
            if not isinstance(point, dict):
                raise IndustrialSiteError(
                    f"assets[{index}].inspection_points[{point_index}] must be an object."
                )
            _text(point.get("point_id"), f"assets[{index}].inspection_points[{point_index}].point_id")
            _text(point.get("measurement"), f"assets[{index}].inspection_points[{point_index}].measurement")
        if asset_id in asset_ids:
            raise IndustrialSiteError(f"Duplicate asset_id: {asset_id}")
        asset_ids.add(asset_id)

    waypoint_asset_ids: set[str] = set()
    for index, waypoint in enumerate(data["waypoints"]):
        asset_id = _text(waypoint.get("asset_id"), f"waypoints[{index}].asset_id")
        if asset_id not in asset_ids:
            raise IndustrialSiteError(
                f"waypoints[{index}] references unknown asset_id: {asset_id}"
            )
        waypoint_asset_ids.add(asset_id)

    sensor_contracts = _list(data.get("sensor_contracts"), "sensor_contracts")
    sensor_ids: set[str] = set()
    for index, contract in enumerate(sensor_contracts):
        if not isinstance(contract, dict):
            raise IndustrialSiteError(f"sensor_contracts[{index}] must be an object.")
        sensor_id = _text(contract.get("sensor_id"), f"sensor_contracts[{index}].sensor_id")
        _text(contract.get("channel"), f"sensor_contracts[{index}].channel")
        _text(contract.get("unit"), f"sensor_contracts[{index}].unit")
        _text(contract.get("source_status"), f"sensor_contracts[{index}].source_status")
        if sensor_id in sensor_ids:
            raise IndustrialSiteError(f"Duplicate sensor_id: {sensor_id}")
        sensor_ids.add(sensor_id)

    safety = data.get("safety")
    if not isinstance(safety, dict):
        raise IndustrialSiteError("safety is required for an industrial site.")
    for key in ("restricted_zones", "stop_conditions", "human_review_required"):
        _list(safety.get(key), f"safety.{key}")

    if waypoint_asset_ids != asset_ids:
        missing = sorted(asset_ids - waypoint_asset_ids)
        raise IndustrialSiteError(
            "Every registered asset must have an inspection waypoint; missing: "
            + ", ".join(missing)
        )
    return data


def industrial_readiness(data: dict[str, Any]) -> dict[str, Any]:
    assets = data.get("assets", [])
    model_status_counts = {key: 0 for key in ("procedural_proxy", "cad_pending", "field_verified")}
    for asset in assets:
        status = asset.get("model_status")
        if status in model_status_counts:
            model_status_counts[status] += 1
    sensors = data.get("sensor_contracts", [])
    source_counts: dict[str, int] = {}
    for sensor in sensors:
        status = str(sensor.get("source_status", "unknown"))
        source_counts[status] = source_counts.get(status, 0) + 1
    field_ready = (
        bool(assets)
        and model_status_counts["cad_pending"] == 0
        and model_status_counts["field_verified"] == len(assets)
        and all(sensor.get("source_status") == "field_verified" for sensor in sensors)
    )
    return {
        "status": "FIELD_READY" if field_ready else "SIMULATION_READY_FIELD_DATA_PENDING",
        "asset_count": len(assets),
        "waypoint_count": len(data.get("waypoints", [])),
        "sensor_contract_count": len(sensors),
        "model_status_counts": model_status_counts,
        "sensor_source_counts": source_counts,
        "field_deployment_blockers": [
            "CAD or scan provenance is not field_verified.",
            "Sensor calibration and live gateway bindings are not field_verified.",
            "Safety acceptance and site commissioning evidence are required.",
        ] if not field_ready else [],
    }
