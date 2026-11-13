from __future__ import annotations
from datetime import datetime, timezone
import hashlib
from ..models import Anomaly, Assessment, Observation, Severity, Waypoint, WorkOrder

def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

def _max_severity(anomalies: list[Anomaly]) -> Severity:
    if not anomalies:
        return Severity.NORMAL
    rank = {Severity.NORMAL: 0, Severity.UNKNOWN: 1, Severity.WARNING: 2, Severity.CRITICAL: 3}
    return max((item.severity for item in anomalies), key=lambda item: rank[item])

class RuleBasedDiagnosticEngine:
    """Transparent deterministic baseline; not an ML model or causal diagnosis."""
    def assess(self, observation: Observation, waypoint: Waypoint) -> Assessment:
        anomalies: list[Anomaly] = []
        required_values: list[tuple[str, object | None]] = [("temperature_c", observation.temperature_c)]
        if waypoint.pressure_max_mpa is not None:
            required_values.append(("pressure_mpa", observation.pressure_mpa))
        if waypoint.require_door_closed:
            required_values.append(("cabinet_door_closed", observation.cabinet_door_closed))

        observed_count = sum(value is not None for _, value in required_values)
        if observation.leak_detected is not None:
            observed_count += 1

        missing_required = [name for name, value in required_values if value is None]
        if missing_required:
            anomalies.append(Anomaly(
                "MEASUREMENT_MISSING", Severity.UNKNOWN,
                "一个或多个必需测量缺失，不能将该设备判定为正常。",
                {"missing_fields": missing_required},
            ))

        if observation.pressure_mpa is not None and waypoint.pressure_max_mpa is not None:
            value = observation.pressure_mpa
            if value > waypoint.pressure_max_mpa * 1.10:
                anomalies.append(Anomaly("PRESSURE_CRITICAL", Severity.CRITICAL,
                    f"压力 {value:.3f} MPa 显著高于配置上限 {waypoint.pressure_max_mpa:.3f} MPa。",
                    {"pressure_mpa": value, "configured_max_mpa": waypoint.pressure_max_mpa}))
            elif value > waypoint.pressure_max_mpa:
                anomalies.append(Anomaly("PRESSURE_HIGH", Severity.WARNING,
                    f"压力 {value:.3f} MPa 超过配置上限 {waypoint.pressure_max_mpa:.3f} MPa。",
                    {"pressure_mpa": value, "configured_max_mpa": waypoint.pressure_max_mpa}))

        if observation.temperature_c is not None:
            value = observation.temperature_c
            if value >= waypoint.critical_temp_c:
                anomalies.append(Anomaly("TEMPERATURE_CRITICAL", Severity.CRITICAL,
                    f"模拟温度 {value:.1f} °C 达到严重告警阈值 {waypoint.critical_temp_c:.1f} °C。",
                    {"temperature_c": value, "critical_threshold_c": waypoint.critical_temp_c}))
            elif value >= waypoint.warning_temp_c:
                anomalies.append(Anomaly("TEMPERATURE_HIGH", Severity.WARNING,
                    f"模拟温度 {value:.1f} °C 达到预警阈值 {waypoint.warning_temp_c:.1f} °C。",
                    {"temperature_c": value, "warning_threshold_c": waypoint.warning_temp_c}))

        if waypoint.require_door_closed and observation.cabinet_door_closed is not None:
            if not observation.cabinet_door_closed:
                anomalies.append(Anomaly("CABINET_DOOR_OPEN", Severity.WARNING,
                    "设备台账要求柜门闭合，但当前模拟状态为未闭合。",
                    {"cabinet_door_closed": False}))

        if observation.leak_detected is True:
            anomalies.append(Anomaly("LEAK_SUSPECTED", Severity.CRITICAL,
                "模拟输入标记为疑似泄漏；需要人工复核，不能仅凭该标记执行联动操作。",
                {"leak_detected": True}))

        if observed_count == 0:
            severity, quality = Severity.UNKNOWN, "NO_USABLE_MEASUREMENTS"
        else:
            severity = _max_severity(anomalies)
            quality = "PARTIAL" if missing_required else "USABLE"
        return Assessment(severity, anomalies, quality, "deterministic_rule_engine")

    def create_work_order(self, observation: Observation, waypoint: Waypoint,
                          assessment: Assessment, site_id: str,
                          run_id: str | None = None) -> WorkOrder:
        digest = hashlib.sha1(
            f"{site_id}|{run_id or ''}|{observation.sample_id}|{observation.device_id}".encode("utf-8")
        ).hexdigest()[:10].upper()
        codes = {item.code for item in assessment.anomalies}
        actions: list[str] = []
        if "TEMPERATURE_CRITICAL" in codes:
            actions.append("安排具备资质的人员复核温度数据、设备负载和测温条件；本系统不直接控制设备。")
        elif "TEMPERATURE_HIGH" in codes:
            actions.append("按设备维护规程复核温度趋势与测温条件。")
        if "PRESSURE_CRITICAL" in codes or "PRESSURE_HIGH" in codes:
            actions.append("由现场人员核对表计读数、量程和设备允许压力，不自动执行泄压。")
        if "CABINET_DOOR_OPEN" in codes:
            actions.append("由授权人员现场确认柜门状态及作业安全条件。")
        if "LEAK_SUSPECTED" in codes:
            actions.append("将疑似泄漏作为待复核线索，遵循现场应急规程；不得仅凭视觉告警自动操作阀门。")
        if assessment.severity == Severity.UNKNOWN:
            actions.append("数据不足，重新采集传感器数据并由人工复核后再判定。")
        if not actions:
            actions.append("当前规则未发现超阈值项；仍应遵循设备既定巡检周期。")
        return WorkOrder(
            ticket_id=f"SIM-WO-{digest}", created_at_utc=utc_now_iso(), site_id=site_id,
            zone=waypoint.zone, robot_id=observation.robot_id, waypoint_id=waypoint.waypoint_id,
            device_id=waypoint.device_id, device_name=waypoint.device_name,
            severity=assessment.severity, source=observation.source,
            observations={
                "asset_id": waypoint.asset_id,
                "pressure_mpa": observation.pressure_mpa,
                "temperature_c": observation.temperature_c,
                "ambient_temperature_c": observation.ambient_temperature_c,
                "cabinet_door_closed": observation.cabinet_door_closed,
                "leak_detected": observation.leak_detected,
                "sensor_confidence": observation.sensor_confidence,
                "model_version": observation.model_version,
                "calibration_version": observation.calibration_version,
                "quality_flags": observation.quality_flags,
                "inference_latency_ms": observation.inference_latency_ms,
                "data_quality": assessment.data_quality,
            },
            anomaly_codes=[item.code for item in assessment.anomalies],
            anomaly_messages=[item.message for item in assessment.anomalies],
            recommended_actions=actions, requires_human_review=True)
